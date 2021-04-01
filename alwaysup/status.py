from typing import List
import enum


class Status(enum.Enum):
    OK = 1
    NOK = 2
    WARNING = 3
    STOPPED = 4


def list_of_status_to_status(statuses: List[Status]) -> Status:
    if all([x == Status.STOPPED for x in statuses]):
        return Status.STOPPED
    if all([x == Status.OK for x in statuses]):
        return Status.OK
    if any([x == Status.NOK for x in statuses]):
        return Status.NOK
    return Status.WARNING
