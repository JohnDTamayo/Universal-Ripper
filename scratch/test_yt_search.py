from ytmusicapi import YTMusic
import json

yt = YTMusic()
results = yt.search("Never Gonna Give You Up", filter="songs", limit=1)
print(json.dumps(results, indent=2))
