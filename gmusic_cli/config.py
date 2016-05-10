import os.path
import yaml

from attr import attributes, attr, validators


valid_str = validators.instance_of(str)

str_attr = attr(validator=valid_str)


@attributes
class Config:
    username = str_attr
    password = str_attr
    device_id = str_attr


def get_config(fname):
    fname = os.path.expanduser(fname)
    fname = os.path.abspath(fname)

    with open(fname) as f:
        config = yaml.load(f)

    return Config(
        username=config['username'],
        password=config['password'],
        device_id=config['device_id'],
    )


