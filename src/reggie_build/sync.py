from typing import Annotated

from cappa import command, Arg

from reggie_build import utils
from reggie_build.command import BaseProjectCommand


@command(name="sync")
class SyncCommand(BaseProjectCommand):
    def __call__(self):
        SyncVersionCommand()()


@command(name="sync-version")
class SyncVersionCommand(BaseProjectCommand):
    version: Annotated[str | None, Arg(short=True, help="Version to sync to")] = None

    def __call__(self):
        version = self.version or utils.git_version() or utils.DEFAULT_VERSION
        print(version)
        print(self.log_level)
        print(self.projects)
