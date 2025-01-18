#!/bin/bash

FILE_PATH="$1"
KEY_NAME="$2"
NEW_VALUE="$3"

echo "File path: $FILE_PATH"
echo "Key: $KEY_NAME"
echo "New value: $NEW_VALUE"

# In lines matching this pattern:
#    <optional spaces><KEY_NAME><spaces> = <spaces>'<OLD_VALUE>'<optional spaces>#<comment> (optional)
# we replace <OLD_VALUE> with <NEW_VALUE>, keeping the # comment (if present).
#
# The sed pattern explanation:
# ^(\s*$KEY_NAME\s*=\s*') : capture group #1 = everything from line start through the opening quote
# [^']*                  : match any characters that are NOT a single quote (the old value)
# (')                    : capture group #2 = the closing quote
# (\s*#.*)?              : capture group #3 = optional spaces + comment
# $                      : end of line
#
# Replacement: \1$NEW_VALUE\2\3
#   - \1 = ( key = ' )
#   - $NEW_VALUE = the new replacement text
#   - \2 = the closing single quote
#   - \3 = the optional trailing comment
#
sed -i "s|^\(\s*$KEY_NAME\s*=\s*'\)[^']*\('\)\(\s*#.*\)\?$|\1$NEW_VALUE\2\3|" "$FILE_PATH"

# Verification:
# Check that the file now contains the key = 'NEW_VALUE' (with optional trailing comment).
CHANGED_LINE=$(grep -E "^\s*$KEY_NAME\s*=\s*'$NEW_VALUE'(\s*#.*)?$" "$FILE_PATH")

if [ -n "$CHANGED_LINE" ]; then
    echo "Successfully updated '$KEY_NAME' to '$NEW_VALUE' in $FILE_PATH"
else
    echo "Error: Could not verify the update for '$KEY_NAME' in $FILE_PATH"
fi

# Always keep a small sleep before exit
sleep 0.5
exit 0
