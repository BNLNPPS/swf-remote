#!/usr/bin/env python3
"""Render the devcloud SVG favicon to a conventional multi-size ICO file."""
import argparse
from pathlib import Path
import shutil
import subprocess
import tempfile
from urllib.request import urlopen
from xml.etree import ElementTree

from PIL import Image

LOGO_SOURCE = 'https://wiki.bnl.gov/EPIC/images/9/90/EPIC-logo_black.svg'


def refresh_outline(public):
    with urlopen(LOGO_SOURCE, timeout=15) as source:
        root = ElementTree.fromstring(source.read())
    path = root.find('.//*[@id="path1122"]')
    if path is None:
        raise ValueError('Official logo lowercase e outline is missing')
    (public / 'favicon.svg').write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="256" height="256" viewBox="0 0 96 96">\n'
        '  <title>ePIC devcloud</title>\n'
        f'  <!-- Lowercase e outline from {LOGO_SOURCE} -->\n'
        f'  <path fill="#ed2024" transform="translate(6 83)" d="{path.attrib["d"]}"/>\n'
        '</svg>\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--chromium', default=shutil.which('chromium'))
    parser.add_argument('--refresh-outline', action='store_true',
                        help='Fetch the original lowercase e from the collaboration logo')
    args = parser.parse_args()
    if not args.chromium:
        parser.error('Chromium is required')
    public = Path(__file__).resolve().parent.parent / 'public'
    if args.refresh_outline:
        refresh_outline(public)
    with tempfile.TemporaryDirectory(prefix='devcloud-favicon-') as work:
        work = Path(work)
        png = work / 'favicon.png'
        subprocess.run([
            args.chromium, '--headless', '--no-sandbox', '--disable-gpu',
            '--hide-scrollbars', '--no-first-run', '--no-default-browser-check',
            '--default-background-color=00000000', '--force-device-scale-factor=1',
            '--window-size=256,256', f'--user-data-dir={work / "profile"}',
            f'--screenshot={png}', (public / 'favicon.svg').as_uri(),
        ], check=True, timeout=30, stdout=subprocess.DEVNULL)
        with Image.open(png) as image:
            if image.size != (256, 256):
                raise ValueError(f'Unexpected render size: {image.size}')
            image.save(public / 'favicon.ico', sizes=[(16, 16), (32, 32), (48, 48)])
    print(f'Wrote {public / "favicon.ico"}')


if __name__ == '__main__':
    main()
