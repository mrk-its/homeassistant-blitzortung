MANIFEST_FILE="custom_components/blitzortung/manifest.json"
TMPFILE=$(mktemp /tmp/blitzortung-manifest.XXXXXX)
cp $MANIFEST_FILE $TMPFILE
jq '.version="'$1'"' < $TMPFILE > $MANIFEST_FILE
sed -i 's/^__version__ = .*/__version__ = "'"$1"'"/' custom_components/blitzortung/version.py
rm $TMPFILE
