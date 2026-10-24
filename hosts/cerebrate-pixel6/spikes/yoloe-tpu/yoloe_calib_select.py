"""int8 calibration set for YOLOE: COCO val2017 indoor photos ("rooms first"),
selected by COCO's annotations -- at least two instances of room-object
categories, at least one of them a large indoor anchor (bed, couch, dining
table, toilet, tv, refrigerator, oven, sink) -- excluding every COCO image
the lane's test photos come from (browser-perception SOURCES.md). Writes the
list and downloads the images.  usage: <annotations json> <out dir> <count>"""
import sys, json, re, random, urllib.request, os
ANN, OUT, N = sys.argv[1], sys.argv[2], int(sys.argv[3])
ROOM = {"bed", "couch", "chair", "dining table", "toilet", "tv", "laptop", "potted plant", "sink", "oven", "refrigerator",
        "book", "clock", "vase", "suitcase", "backpack", "handbag", "microwave", "remote", "cup", "bottle", "keyboard", "mouse"}
ANCHOR = {"bed", "couch", "dining table", "toilet", "tv", "refrigerator", "oven", "sink"}
excl = set()
for f in ("/Users/dev/Code/browser-perception/demos/object-selection/samples/SOURCES.md", "/Users/dev/Code/browser-perception/demos/segmentation/samples/SOURCES.md"):
    excl |= {int(m) for m in re.findall(r"COCO 2017 (?:val|train) (\d+)", open(f).read())}
d = json.load(open(ANN)); cats = {c["id"]: c["name"] for c in d["categories"]}
per = {}
for a in d["annotations"]:
    per.setdefault(a["image_id"], []).append(cats[a["category_id"]])
ok = [i for i, names in per.items() if i not in excl and sum(n in ROOM for n in names) >= 2 and any(n in ANCHOR for n in names)]
random.Random(0).shuffle(ok); sel = sorted(ok[:N])
os.makedirs(OUT, exist_ok=True)
open(f"{OUT}/list.txt", "w").write("\n".join(str(i) for i in sel) + "\n")
print(f"excluded {len(excl)} test-photo ids; {len(ok)} candidates; selected {len(sel)}", flush=True)
for k, i in enumerate(sel):
    p = f"{OUT}/{i:012d}.jpg"
    if not os.path.exists(p): urllib.request.urlretrieve(f"http://images.cocodataset.org/val2017/{i:012d}.jpg", p)
print("downloaded", len(os.listdir(OUT)) - 1)
