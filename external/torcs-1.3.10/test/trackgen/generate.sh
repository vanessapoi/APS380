#!/bin/bash

# run trackgen on all files, generate result to "generated"
# path to trackgen is expected as first parameter, e.g. ~/torcs_bin/bin/trackgen

[ -z "$1" ] && exit 1
[ ! -f "$1" ] && exit 1
root=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
status=0

while IFS= read -r -d '' f; do
	path=${f%/*}
	name=${path##*/}
	categorypath=${path%/*}
	category=${categorypath##*/}
	genpath=${path/source/generated}
#   Generate "sources"
#	$1 -c $category -n $name -i $path -o $path -a

#   Generate "generated"
	if ! "$1" -q -c "$category" -n "$name" -i "$path" -o "$genpath" -a < /dev/null; then
		echo "trackgen failed: $category/$name" >&2
		status=1
	fi
done < <(find "$root/source" -name '*.xml' -print0)

exit $status
