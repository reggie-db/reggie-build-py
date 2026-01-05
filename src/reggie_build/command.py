import json
import shlex
from abc import abstractmethod, ABC
from typing import Annotated, Any

from cappa import Arg, Env, ArgAction, default_parse

from pydantic import BaseModel
from cappa.type_view import TypeView


def parse_list(value, type_view: TypeView) -> Any:
    elements: list | None = None
    if isinstance(value, list):
        elements = value
    elif value is not None:
        value_stripped = str(value).strip()
        if value_stripped.startswith("[") and value_stripped.endswith("]"):
            try:
                elements = json.loads(value_stripped)
            except json.JSONDecodeError:
                pass
        if elements is None:
            elements = shlex.split(value)
    return (
        [default_parse(v, type_view=type_view.inner_types[0]) for v in elements]
        if elements is not None
        else []
    )


class BaseCommand(BaseModel, ABC):
    log_level: Annotated[
        str,
        Arg(
            long="log-level",
            default=Env("LOG_LEVEL", default="INFO"),
            help="Optional log level to use for the command",
        ),
    ] = "INFO"

    @abstractmethod
    def __call__(self):
        pass


class BaseProjectCommand(BaseCommand, ABC):
    projects: Annotated[
        list[str],
        Arg(
            long="project",
            short=True,
            default=Env("PROJECTS"),
            parse=parse_list,
            action=ArgAction.append,
            help="Optional list of project names or identifiers to run the command on",
        ),
    ] = []


class TestCommand(BaseCommand):
    def __call__(self):
        print(self.log_level)


class TestCommand2(BaseCommand):
    def __call__(self):
        print(self.log_level)
