"""从 .deb（ar 归档）提取 data.tar.xz 里的 wqy-microhei.ttc（v2：只匹配字体）。"""
import io
import tarfile

ar = open("wqy.deb", "rb").read()
pos = 8
while pos < len(ar):
    hdr = ar[pos:pos + 60]
    name = hdr[0:16].decode().strip()
    size = int(hdr[48:58].decode().strip())
    data_start = pos + 60
    data = ar[data_start:data_start + size]
    print(f"成员: {name} ({size} bytes)")
    if name == "data.tar.xz":
        tf = tarfile.open(fileobj=io.BytesIO(data), mode="r:xz")
        for m in tf.getmembers():
            if m.isfile() and (m.name.endswith(".ttc") or m.name.endswith(".ttf")):
                out = m.name.split("/")[-1]
                open(out, "wb").write(tf.extractfile(m).read())
                print(f"已提取 → {out} ({m.size} bytes)")
        break
    pos = data_start + size + (size % 2)