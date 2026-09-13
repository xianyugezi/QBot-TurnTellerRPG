# -*- coding: utf-8 -*-
"""九期238：cloudsea 内容包打包——content/cloudsea → dist/cloudsea_content.zip
前置：verify_cloudsea 三段探针全绿（本脚本不重复校验，CI 由 job 串联）。
"""
import io, os, zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # scripts/x.py → scripts → TTR 根
CLOUD = os.path.join(ROOT, 'content', 'cloudsea')
DIST = os.path.join(ROOT, 'dist')


def main() -> int:
    os.makedirs(DIST, exist_ok=True)
    out = os.path.join(DIST, 'cloudsea_content.zip')
    n = 0
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
        for root, _dirs, files in os.walk(CLOUD):
            for fn in files:
                fp = os.path.join(root, fn)
                arc = os.path.relpath(fp, CLOUD)
                z.write(fp, os.path.join('cloudsea', arc))
                n += 1
    print('packaged %d files -> %s (%d bytes)' % (
        n, out, os.path.getsize(out)))
    return 0


if __name__ == '__main__':
    sys_exit = main()
    raise SystemExit(sys_exit)
