import click

from .drudge import cli as cli_drudge
from .lighthouse import cli as cli_lighthouse
from .us_right_wing import cli as cli_us_right_wing

cli_group = click.CommandCollection(
    sources=[
        cli_drudge,
        cli_lighthouse,
        cli_us_right_wing,
    ]
)

if __name__ == "__main__":
    cli_group()
