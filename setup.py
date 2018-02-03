import os

from distutils.core import setup

here = os.path.dirname(__file__)


def get_reqs(fname):
    fname = os.path.join(here, 'reqs', fname)
    return [
        req for req in open(fname, 'r').readlines()
        if req and req[0] != '-'
    ]


setup(
    name='gmusic-cli',
    version='0.0.1',
    description='GMusic CLI',
    entry_points={
        'console_scripts': [
            'gmusic-cli = gmusic_cli.cli:cli',
        ]
    },
    install_requires=get_reqs('install.txt')
)
