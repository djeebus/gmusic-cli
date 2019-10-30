import os.path
import yaml

from attr import attributes, attr, validators, asdict


valid_str = validators.instance_of(str)

optional_str_attr = attr(
    validator=validators.optional(valid_str),
    default='',
)


@attributes
class Config:
    username = optional_str_attr
    password = optional_str_attr


def get_config(path):

    if not os.path.exists(path):
        return Config()

    with open(path) as f:
        config = yaml.safe_load(f)

    return Config(
        username=config['username'],
        password=config['password'],
    )


def set_config(path, config: Config):
    config = asdict(config)

    with open(path, 'w') as fp:
        yaml.safe_dump(config, fp)
