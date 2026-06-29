import datetime
from dataclasses import dataclass
from typing import Optional

from icalendar import Calendar, Todo


@dataclass
class CalendarTask:
    task_uid: str
    title: str
    status: str
    created_at: datetime.datetime
    updated_at: datetime.datetime
    due_date: Optional[datetime.datetime] = None


def generate_ics_from_task(task: CalendarTask) -> str:
    """
    Generates a basic CalDAV-compatible .ics (iCalendar) string for a TicketTask (VTODO).
    """
    ics_status = "NEEDS-ACTION"
    if task.status == "in_progress":
        ics_status = "IN-PROCESS"
    elif task.status == "done":
        ics_status = "COMPLETED"
    elif task.status == "blocked":
        ics_status = "NEEDS-ACTION"

    cal = Calendar()
    cal.add('VERSION', '2.0')
    cal.add('PRODID', '-//Naruon//AI Workspace//EN')

    todo = Todo()
    todo.add('UID', task.task_uid)
    todo.add('CREATED', task.created_at)
    todo.add('DTSTAMP', task.updated_at)
    todo.add('SUMMARY', task.title)
    todo.add('STATUS', ics_status)

    if task.due_date:
        todo.add('DUE', task.due_date)

    cal.add_component(todo)

    return cal.to_ical().decode("utf-8")
