/*
 * mosquitto_area_limit: refuse subscriptions that cover too much of the globe.
 *
 * Strikes are published on <root>/<g1>/.../<g12>, one geohash character per level.
 * A SUBSCRIBE from an anonymous client is refused when, for any configured root, the
 * filter would receive strikes while fixing fewer than `min_levels` geohash characters
 * ('+' doesn't count as fixed). With min_levels 1 that refuses #, +/#, blitzortung/#,
 * blitzortung/1.1/# and blitzortung/1.1/+/#, and allows blitzortung/1.1/u/#.
 *
 * Clients whose ID starts with one of `deny_client_prefixes` get every SUBSCRIBE refused.
 * Authenticated clients (with a username) are never restricted. Everything else is
 * passed on (MOSQ_ERR_PLUGIN_DEFER), so the acl_file still decides as before.
 *
 * Options (mosquitto.conf):
 *   plugin /usr/lib/x86_64-linux-gnu/mosquitto_area_limit.so
 *   plugin_opt_roots blitzortung/1.1,b/1
 *   plugin_opt_min_levels 1
 *   plugin_opt_deny_client_prefixes fae-relay
 */
#include <stdbool.h>
#include <stdlib.h>
#include <string.h>

#include <mosquitto.h>
#include <mosquitto_broker.h>
#include <mosquitto_plugin.h>

#define MAX_ROOTS 8
#define MAX_PREFIXES 16
#define MAX_LEVELS 32

struct config {
	char *roots[MAX_ROOTS];
	int root_count;
	char *prefixes[MAX_PREFIXES];
	int prefix_count;
	int min_levels;
};

static mosquitto_plugin_id_t *plugin_id;
static struct config cfg;

/* Split `text` at `sep` in place into at most `max` parts; returns the part count. */
static int split(char *text, char sep, char **parts, int max)
{
	int n = 0;
	char *start = text;

	for(char *p = text; ; p++){
		if(*p == sep || *p == '\0'){
			bool end = (*p == '\0');
			*p = '\0';
			if(n == max){
				return -1;
			}
			parts[n++] = start;
			if(end){
				return n;
			}
			start = p + 1;
		}
	}
}

/*
 * Number of geohash levels the filter fixes under `root`, or -1 if it can't receive
 * anything published under that root.
 */
static int fixed_levels(char **filter, int filter_len, char **root, int root_len)
{
	int i;
	int fixed = 0;

	for(i = 0; i < root_len; i++){
		if(i >= filter_len){
			return -1;
		}
		if(!strcmp(filter[i], "#")){
			return 0;
		}
		if(strcmp(filter[i], "+") && strcmp(filter[i], root[i])){
			return -1;
		}
	}
	for(; i < filter_len; i++){
		if(!strcmp(filter[i], "#")){
			break;
		}
		if(strcmp(filter[i], "+")){
			fixed++;
		}
	}
	return fixed;
}

/* True if the filter receives strikes under some root with too few fixed levels. */
static bool too_broad(const char *topic)
{
	char filter_buf[1024];
	char root_buf[256];
	char *filter[MAX_LEVELS];
	char *root[MAX_LEVELS];
	int filter_len;

	if(strlen(topic) >= sizeof(filter_buf)){
		return false;
	}
	strcpy(filter_buf, topic);
	filter_len = split(filter_buf, '/', filter, MAX_LEVELS);
	if(filter_len < 0){
		return false;  /* deeper than any strike topic: can't be broad */
	}
	for(int r = 0; r < cfg.root_count; r++){
		int root_len;
		int fixed;

		strncpy(root_buf, cfg.roots[r], sizeof(root_buf) - 1);
		root_buf[sizeof(root_buf) - 1] = '\0';
		root_len = split(root_buf, '/', root, MAX_LEVELS);
		fixed = fixed_levels(filter, filter_len, root, root_len);
		if(fixed >= 0 && fixed < cfg.min_levels){
			return true;
		}
	}
	return false;
}

static bool denied_client(const char *id)
{
	if(id == NULL){
		return false;
	}
	for(int i = 0; i < cfg.prefix_count; i++){
		if(!strncmp(id, cfg.prefixes[i], strlen(cfg.prefixes[i]))){
			return true;
		}
	}
	return false;
}

static int acl_check(int event, void *event_data, void *userdata)
{
	struct mosquitto_evt_acl_check *ed = event_data;
	const char *id;
	(void)event;
	(void)userdata;

	if(ed->access != MOSQ_ACL_SUBSCRIBE || mosquitto_client_username(ed->client) != NULL){
		return MOSQ_ERR_PLUGIN_DEFER;
	}
	id = mosquitto_client_id(ed->client);
	if(denied_client(id)){
		mosquitto_log_printf(MOSQ_LOG_NOTICE, "area_limit: refused %s for client %s (client id)",
				ed->topic, id ? id : "?");
		return MOSQ_ERR_ACL_DENIED;
	}
	if(too_broad(ed->topic)){
		mosquitto_log_printf(MOSQ_LOG_NOTICE, "area_limit: refused %s for client %s (area)",
				ed->topic, id ? id : "?");
		return MOSQ_ERR_ACL_DENIED;
	}
	return MOSQ_ERR_PLUGIN_DEFER;
}

int mosquitto_plugin_version(int supported_version_count, const int *supported_versions)
{
	for(int i = 0; i < supported_version_count; i++){
		if(supported_versions[i] == 5){
			return 5;
		}
	}
	return -1;
}

int mosquitto_plugin_init(mosquitto_plugin_id_t *identifier, void **userdata,
		struct mosquitto_opt *opts, int opt_count)
{
	(void)userdata;
	plugin_id = identifier;
	memset(&cfg, 0, sizeof(cfg));
	cfg.min_levels = 1;

	for(int i = 0; i < opt_count; i++){
		if(!strcmp(opts[i].key, "roots")){
			cfg.root_count = split(strdup(opts[i].value), ',', cfg.roots, MAX_ROOTS);
		}else if(!strcmp(opts[i].key, "min_levels")){
			cfg.min_levels = atoi(opts[i].value);
		}else if(!strcmp(opts[i].key, "deny_client_prefixes")){
			if(opts[i].value[0] != '\0'){
				cfg.prefix_count = split(strdup(opts[i].value), ',', cfg.prefixes, MAX_PREFIXES);
			}
		}else{
			mosquitto_log_printf(MOSQ_LOG_ERR, "area_limit: unknown option %s", opts[i].key);
			return MOSQ_ERR_INVAL;
		}
	}
	if(cfg.root_count <= 0 || cfg.prefix_count < 0){
		mosquitto_log_printf(MOSQ_LOG_ERR, "area_limit: plugin_opt_roots is required (max %d), at most %d prefixes",
				MAX_ROOTS, MAX_PREFIXES);
		return MOSQ_ERR_INVAL;
	}
	mosquitto_log_printf(MOSQ_LOG_NOTICE, "area_limit: %d roots, min_levels %d, %d denied client prefixes",
			cfg.root_count, cfg.min_levels, cfg.prefix_count);
	return mosquitto_callback_register(plugin_id, MOSQ_EVT_ACL_CHECK, acl_check, NULL, NULL);
}

int mosquitto_plugin_cleanup(void *userdata, struct mosquitto_opt *opts, int opt_count)
{
	(void)userdata;
	(void)opts;
	(void)opt_count;
	return mosquitto_callback_unregister(plugin_id, MOSQ_EVT_ACL_CHECK, acl_check, NULL);
}
