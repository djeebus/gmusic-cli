from distutils.core import setup


setup(
    name='gmusic-cli',
    version='0.0.1',
    description='GMusic CLI',
    entry_points={
        'console_scripts': [
            'gmusic-cli = gmusic_cli.cli:cli',
        ]
    }
)
