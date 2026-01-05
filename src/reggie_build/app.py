from dataclasses import dataclass

import cappa
from cappa import Subcommands

from reggie_build.command import TestCommand2, TestCommand
from reggie_build import sync


@dataclass
class InvokeCommand:
    subcommand: Subcommands[
        TestCommand2 | TestCommand | sync.SyncCommand | sync.SyncVersionCommand
    ]


if __name__ == "__main__":
    cappa.invoke(InvokeCommand)
