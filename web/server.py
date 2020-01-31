from flask import Flask
from flask import escape, request, redirect, render_template, abort
from wtforms import Form, BooleanField, SelectField, StringField, TextAreaField, validators, IntegerField, ValidationError, SelectMultipleField
from wtforms.validators import StopValidation
from wtforms.widgets.html5 import NumberInput
import os
import re
import json
import datetime
import psycopg2

from env import build_env
from env import Default

cwd = os.path.dirname(os.path.realpath(__file__))

ENV_VAR_PREFIX = "PG_TIMETABLE"
ENV = build_env(
    ENV_VAR_PREFIX,
    {
        "DBNAME": Default("timetable"),
        "USER": Default("postgres"),
        "PASSWORD": Default(""),
        "HOST": Default("localhost"),
    },
)

class Object(object):
    def __init__(self, **kwargs):
        self.__keys__ = []
        for key, value in kwargs.items():
            self.__keys__.append(key)
            setattr(self, key, value)

    def __repr__(self):
        items=[]
        for key in self.__keys__:
            value = getattr(self, key, None)
            items.append(f"{key}={value}")
        return "Object({})".format(", ".join(items))

app = Flask(__name__, static_url_path='/static')
#app.config['EXPLAIN_TEMPLATE_LOADING'] = True

class JSONField(TextAreaField):
    def _value(self):
        return json.dumps(self.data) if self.data else ''

    def process_formdata(self, valuelist):
        if valuelist:
            try:
                self.data = json.loads(valuelist[0])
            except ValueError:
                raise ValueError('This field contains invalid JSON')
        else:
            try:
                self.data = json.loads(self.data)
            except (ValueError, TypeError):
                pass

    def pre_validate(self, form):
        super().pre_validate(form)
        if self.data:
            try:
                json.dumps(self.data)
            except TypeError:
                raise ValueError('This field contains invalid JSON')

class Model(object):
    def __init__(self, **kwargs):
        self.conn = psycopg2.connect(
            "dbname={dbname} user={user} password={password} host={host}".format(
                dbname=ENV.dbname, user=ENV.user, password=ENV.password, host=ENV.host
            )
        )
        self.cur = self.conn.cursor()
        self.parents_done = []
        self.update(**kwargs)

    def update(self, **kwargs):
        for key, value in kwargs.items():
            setattr(self, key, value)

    def get_all_tasks(self):
        self.cur.execute("SELECT task_id, name, kind, script FROM timetable.base_task order by task_id")
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(task_id=row[0], task_name=row[1], task_kind=row[2], task_function=row[3]))

        return result

    def get_task_by_id(self, task_id):
        self.cur.execute(
            "SELECT name, kind, script FROM timetable.base_task where task_id = %s", (task_id,))
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        result = Object(task_id=task_id, task_name=row[0], task_kind=row[1], task_function=row[2])
        return result

    def get_task_by_name(self, task_name):
        self.cur.execute(
            "SELECT task_id, name, kind, script FROM timetable.base_task where name = %s", (task_name,))
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        result = Object(task_id=row[0], task_name=row[1], task_kind=row[2], task_function=row[3])
        return result


    def save_task(self):
        if self.task_id is None:
            self.cur.execute(
                "INSERT INTO timetable.base_task (name, kind, script) VALUES (%s, %s, %s)", (self.task_name, self.task_kind, self.task_function)
            )
        else:
            self.cur.execute(
                "UPDATE timetable.base_task set name = %s, kind = %s, script = %s where task_id = %s AND kind != 'BUILTIN'", (self.task_name, self.task_kind, self.task_function, self.task_id))
        self.conn.commit()


    def save_db_connection(self):
        if self.database_connection is None:
            self.cur.execute(
                "INSERT INTO timetable.database_connection (connect_string, comment) VALUES (%s, %s)", (self.connect_string, self.comment)
            )
        else:
            self.cur.execute(
                "UPDATE timetable.database_connection set connect_string = %s, comment = %s where database_connection = %s", (self.connect_string, self.comment, self.database_connection))
        self.conn.commit()

    def get_chain_by_id(self, chain_id):
        self.cur.execute("SELECT chain_id, parent_id, task_id, run_uid, database_connection, ignore_error FROM timetable.task_chain where chain_id = %s", (chain_id,))
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        result = Object(chain_execution_config=self.chain_execution_config, chain_id=row[0], task_id=row[2], parent_id=row[1], run_uid=row[3], database_connection=row[4], ignore_error=row[5], next=self.get_chain_by_parent(parent_id=row[0]), parameters=self.get_chain_parameters(chain_id=row[0]), task=self.get_task_by_id(task_id=row[2]))
        return result

    def get_chain_by_parent(self, parent_id):
        if parent_id not in self.parents_done:
            self.parents_done.append(parent_id)
        else:
            return None
        self.cur.execute("SELECT chain_id, parent_id, task_id, run_uid, database_connection, ignore_error FROM timetable.task_chain where parent_id = %s", (parent_id,))
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        result = Object(chain_execution_config= self.chain_execution_config, chain_id=row[0], parent_id=row[1], run_uid=row[3], database_connection=row[4], ignore_error=row[5], next=self.get_chain_by_parent(parent_id=row[0]), parameters=self.get_chain_parameters(chain_id=row[0]), task=self.get_task_by_id(task_id=row[2]))
        return result


    def get_chain_parameters(self, chain_id):
        if not hasattr(self, "chain_execution_config"):
            return None
        self.cur.execute(
            "SELECT order_id, value FROM timetable.chain_execution_parameters where chain_id = %s and chain_execution_config = %s order by order_id", (chain_id, self.chain_execution_config)
        )
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(chain_execution_config=self.chain_execution_config, chain_id=chain_id, order_id=row[0], value=json.dumps(row[1])))
        return result

    def get_chain_parameter_by_id(self, chain_execution_config, chain_id, order_id):
        self.cur.execute(
            "SELECT chain_execution_config, chain_id, order_id, value FROM timetable.chain_execution_parameters where chain_execution_config = %s and chain_id = %s and order_id = %s", (chain_execution_config, chain_id, order_id)
        )
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        result = Object(chain_execution_config=row[0], chain_id=row[1], order_id=row[2], value=json.dumps(row[3]))
        return result


    def get_all_chains(self, only_base=True):
        if only_base:
            self.cur.execute("SELECT chain_id, task_id, run_uid, database_connection, ignore_error FROM timetable.task_chain where parent_id is null")
        else:
            self.cur.execute("SELECT chain_id, task_id, run_uid, database_connection, ignore_error FROM timetable.task_chain")
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(chain_execution_config=self.chain_execution_config if hasattr(self, "chain_execution_config") else None, chain_id=row[0], run_uid=row[2], database_connection=row[3], ignore_error=row[4], task=self.get_task_by_id(task_id=row[1])))

        return result

    def chains_notparents(self):
        self.cur.execute("select a.chain_id, a.parent_id, a.task_id, a.run_uid, a.database_connection, a.ignore_error FROM timetable.task_chain a left outer join timetable.task_chain b on a.chain_id = b.parent_id where b.parent_id is null")
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(chain_id=row[0], parent_id=row[1], run_uid=row[3], database_connection=row[4], ignore_error=row[5], task=self.get_task_by_id(task_id=row[2])))

        return result

    def save_chain(self):
        if self.chain_id is None:
            self.cur.execute("SELECT chain_id, parent_id, task_id, run_uid, database_connection, ignore_error FROM timetable.task_chain where parent_id = %s", (self.parent_id,))
            records = self.cur.fetchall()
            if len(records) == 0:
                self.cur.execute(
                    "INSERT INTO timetable.task_chain (parent_id, task_id, run_uid, database_connection, ignore_error) VALUES (%s, %s, %s, %s, %s)", (self.parent_id, self.task_id, self.run_uid, self.database_connection, self.ignore_error)
                )
            else:
                row = records[0]
                self.cur.execute(
                    "UPDATE timetable.task_chain set parent_id = Null where chain_id = %s", (row[0],))
                self.cur.execute(
                    "INSERT INTO timetable.task_chain (parent_id, task_id, run_uid, database_connection, ignore_error) VALUES (%s, %s, %s, %s, %s) RETURNING chain_id", (self.parent_id, self.task_id, self.run_uid, self.database_connection, self.ignore_error)
                )
                chain_id = self.cur.fetchone()[0]
                self.cur.execute(
                    "UPDATE timetable.task_chain set parent_id = %s where chain_id = %s", (chain_id, row[0],))
        else:
            self.cur.execute(
                "UPDATE timetable.task_chain set task_id = %s, run_uid = %s, database_connection = %s, ignore_error = %s where chain_id = %s", (self.task_id, self.run_uid, self.database_connection, self.ignore_error, self.chain_id,))
        self.conn.commit()

    def delete_chain(self):
        self.cur.execute("SELECT chain_id, parent_id, task_id, run_uid, database_connection, ignore_error FROM timetable.task_chain where parent_id = %s", (self.chain_id,))
        records = self.cur.fetchall()
        if len(records) == 0:
            self.cur.execute(
                    "delete from timetable.task_chain where chain_id = %s", (self.chain_id,))
        else:
            row = records[0]
            self.cur.execute("SELECT parent_id FROM timetable.task_chain where chain_id = %s", (self.chain_id,))
            parent_id = self.cur.fetchone()[0]
            if parent_id is not None:
                self.cur.execute(
                    "UPDATE timetable.task_chain set parent_id = Null where chain_id = %s", (self.chain_id,))
                self.cur.execute(
                    "UPDATE timetable.task_chain set parent_id = %s where chain_id = %s", (parent_id, row[0],))
                self.cur.execute(
                        "delete from timetable.task_chain where chain_id = %s", (self.chain_id,))
            else:
                self.cur.execute("SELECT chain_id FROM timetable.task_chain where parent_id = %s", (self.chain_id,))
                records = self.cur.fetchall()
                if len(records) == 0:
                    self.cur.execute(
                        "delete from timetable.task_chain where chain_id = %s", (self.chain_id,))
                else:
                    row = records[0]
                    self.cur.execute(
                        "UPDATE timetable.chain_execution_config SET chain_id = %s where chain_id = %s", (row[0], self.chain_id))
                    self.cur.execute(
                        "UPDATE timetable.task_chain set parent_id = Null where parent_id = %s", (self.chain_id,))
                    self.cur.execute(
                        "delete from timetable.task_chain where chain_id = %s", (self.chain_id,))
        self.conn.commit()

    def delete_chain_parameter(self):
        self.cur.execute(
                "delete from timetable.chain_execution_parameters where chain_execution_config = %s and chain_id = %s and order_id = %s", (self.chain_execution_config, self.chain_id, self.order_id))
        self.conn.commit()

    def save_chain_parameter(self):
        self.cur.execute(
                "insert into timetable.chain_execution_parameters (chain_execution_config, chain_id, order_id, value) VALUES (%s, %s, %s, %s) ON CONFLICT (chain_execution_config, chain_id, order_id) DO UPDATE set value = %s", (self.chain_execution_config, self.chain_id, self.order_id, self.value, self.value))
        self.conn.commit()

    def get_last_jobs(self):
        self.cur.execute("select date_trunc('day', last_run), returncode, count(*) as all, count(*) filter (where returncode=0) AS successful, count(*) filter (where returncode<>0) AS failures from timetable.execution_log where last_run >= now() - '1 week'::interval GROUP BY ROLLUP (1, 2);")
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(day=row[0], returncode=row[1], all=row[2], successful=row[3], failures=row[4]))
        return result

    def get_next_jobs(self):
        self.cur.execute("SELECT chain_execution_config, chain_name, timetable.next_run(run_at_minute,run_at_hour,run_at_day,run_at_month,run_at_day_of_week) next_run FROM timetable.chain_execution_config where live = TRUE order by next_run")
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(chain_execution_config=row[0], chain_name=row[1], next_run=row[2]))
        return result


    def get_self_destructive_chains(self):
        self.cur.execute("SELECT chain_execution_config, chain_id, chain_name, run_at_minute, run_at_hour, run_at_day, run_at_month, run_at_day_of_week, max_instances, live, self_destruct, exclusive_execution, excluded_execution_configs, client_name FROM timetable.chain_execution_config where self_destruct=TRUE ")
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(chain_execution_config=row[0], chain_name=row[1], next_run=row[2]))
        return result


    def get_execution_logs(self, chain_execution_config):
        self.cur.execute("SELECT chain_execution_config, chain_id, task_id, name, script,  kind, last_run, finished, returncode, pid FROM timetable.execution_log where chain_execution_config = %s", (chain_execution_config,))
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(chain_execution_config=row[0], chain_id=row[1], task_id=row[2], name=row[3], script=row[4], kind=row[5], last_run=row[6], finished=row[7], returncode=row[8], pid=row[9]))
        return result

    def get_all_db_connections(self):
        self.cur.execute(
            "SELECT database_connection, connect_string, comment FROM timetable.database_connection order by database_connection"
        )
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(database_connection=row[0], connect_string=row[1], comment=row[2], error=validate_db_connection(row[1])))
        return result


    def get_db_connection_by_id(self, database_connection):
        self.cur.execute(
            "SELECT database_connection, connect_string, comment FROM timetable.database_connection where database_connection = %s", (database_connection,)
        )
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        return Object(database_connection=row[0], connect_string=row[1], comment=row[2], error=validate_db_connection(row[1]))


    def get_all_chain_configs(self):
        self.cur.execute(
            "SELECT chain_execution_config, chain_id, chain_name, run_at_minute, run_at_hour, run_at_day, run_at_month, run_at_day_of_week, max_instances, live, self_destruct, exclusive_execution, excluded_execution_configs, client_name FROM timetable.chain_execution_config"
        )
        records = self.cur.fetchall()
        result = []
        for row in records:
            result.append(Object(chain_execution_config=row[0], chain_id=row[1], chain_name=row[2], run_at_minute=row[3], run_at_hour=row[4], run_at_day=row[5], run_at_month=row[6], run_at_day_of_week=row[7], max_instances=row[8], live=row[9], self_destruct=row[10], exclusive_execution=row[11], excluded_execution_configs=row[12], client_name=row[13]))
        return result

    def save_chain_config(self, commit=True):
        if self.chain_execution_config is None and self.chain_id is None and self.task_id is not None:
            self.cur.execute(
                "WITH ins AS (INSERT INTO timetable.task_chain (parent_id, task_id, run_uid, database_connection, ignore_error) VALUES (DEFAULT, %s, DEFAULT, DEFAULT, DEFAULT) RETURNING chain_id) INSERT INTO timetable.chain_execution_config (chain_name, chain_id, run_at_minute, run_at_hour, run_at_day, run_at_month, run_at_day_of_week, max_instances, live, self_destruct, exclusive_execution, excluded_execution_configs, client_name) SELECT %s, chain_id, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s from ins", (self.task_id, self.chain_name, self.run_at_minute, self.run_at_hour, self.run_at_day, self.run_at_month, self.run_at_day_of_week, self.max_instances, self.live, self.self_destruct, self.exclusive_execution, self.excluded_execution_configs, self.client_name))
        elif self.chain_execution_config is None:
            self.cur.execute(
                "INSERT INTO timetable.chain_execution_config (chain_name, chain_id, run_at_minute, run_at_hour, run_at_day, run_at_month, run_at_day_of_week, max_instances, live, self_destruct, exclusive_execution, excluded_execution_configs, client_name) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)", (self.chain_name, self.chain_id, self.run_at_minute, self.run_at_hour, self.run_at_day, self.run_at_month, self.run_at_day_of_week, self.max_instances, self.live, self.self_destruct, self.exclusive_execution, self.excluded_execution_configs, self.client_name))
        else:
            self.cur.execute(
                "UPDATE timetable.chain_execution_config SET chain_execution_config = %s, chain_id = %s, chain_name = %s, run_at_minute = %s, run_at_hour = %s, run_at_day = %s, run_at_month = %s, run_at_day_of_week = %s, max_instances = %s, live = %s, self_destruct = %s, exclusive_execution = %s, excluded_execution_configs = %s, client_name = %s where chain_execution_config = %s", (self.chain_execution_config, self.chain_id, self.chain_name, self.run_at_minute, self.run_at_hour, self.run_at_day, self.run_at_month, self.run_at_day_of_week, self.max_instances, self.live, self.self_destruct, self.exclusive_execution, self.excluded_execution_configs, self.client_name, self.chain_execution_config))
            #In case we want to add more records, we don't want to override existing one
            self.chain_execution_config = None
        if commit:
            self.conn.commit()

    def commit(self):
        self.conn.commit()


    def get_chain_config_by_id(self, id):
        self.cur.execute(
            "SELECT chain_execution_config, chain_id, chain_name, run_at_minute, run_at_hour, run_at_day, run_at_month, run_at_day_of_week, max_instances, live, self_destruct, exclusive_execution, excluded_execution_configs, client_name FROM timetable.chain_execution_config where chain_execution_config = %s", (id,)
        )
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        result = Object(chain_execution_config=row[0], chain_id=row[1], chain_name=row[2], run_at_minute=row[3], run_at_hour=row[4], run_at_day=row[5], run_at_month=row[6], run_at_day_of_week=row[7], max_instances=row[8], live=row[9], self_destruct=row[10], exclusive_execution=row[11], excluded_execution_configs=row[12], client_name=row[13], chain=self.get_chain_by_id(row[1]))
        return result

    def get_chain_config_by_name(self, name):
        self.cur.execute(
            "SELECT chain_execution_config, chain_id, chain_name, run_at_minute, run_at_hour, run_at_day, run_at_month, run_at_day_of_week, max_instances, live, self_destruct, exclusive_execution, excluded_execution_configs, client_name FROM timetable.chain_execution_config where chain_name = %s", (name,)
        )
        records = self.cur.fetchall()
        if len(records) == 0:
            return None
        row = records[0]
        result = Object(chain_execution_config=row[0], chain_id=row[1], chain_name=row[2], run_at_minute=row[3], run_at_hour=row[4], run_at_day=row[5], run_at_month=row[6], run_at_day_of_week=row[7], max_instances=row[8], live=row[9], self_destruct=row[10], exclusive_execution=row[11], excluded_execution_configs=row[12], client_name=row[13])
        return result

def validate_db_connection(s):
    try:
        conn = psycopg2.connect(s)
        conn.close()
        return False
    except Exception as e:
        return e

def empty_or_integer(i):
    if isinstance(i, int) or i is None:
        return i
    elif isinstance(i, str) and not len(i) or i == 'None':
        return None
    return int(i)

class MyBooleanField(BooleanField):
    def process_data(self, value):
        self.data = bool(value)
        self.checked = bool(value)

class ChainForm(Form):
    task_id = SelectField("Task id", coerce=empty_or_integer, choices=[(t.task_id, f'{t.task_id}. {t.task_name}') for t in Model().get_all_tasks()])
    run_uid = StringField("Run uid")
    database_connection = SelectField("Database connection", coerce=empty_or_integer, choices=[(d.database_connection, f'{d.database_connection}. {d.comment}') for d in Model().get_all_db_connections()] + [(None, "No special connection string")])
    ignore_error = MyBooleanField("Ignore error")

class TaskForm(Form):
    task_id = IntegerField("Task id")
    task_name = StringField("Task name")
    task_function = TextAreaField("Task function")
    task_kind = SelectField("Task kind", choices=[(x,x) for x in ["SQL", "SHELL"]])

    def validate_task_name(form, field):
        if field.data is None or field.data == '':
            raise ValidationError("Task name must be set!")
        t = Model().get_task_by_name(field.data)
        if t and hasattr(t, "task_id") and t.task_id != form.task_id.data:
            raise ValidationError("Task name must be unique!")

class DBConnectionForm(Form):
    database_connection = IntegerField("Database connection")
    connect_string = StringField("Connect string")
    comment = TextAreaField("Comment")

    def validate_connect_string(form, field):
        error = validate_db_connection(field.data)
        if error:
            raise ValidationError(error)

class ChainExecutionParametersForm(Form):
    order_id = IntegerField("Order id")
    value = JSONField("Value")

def run_at_filter(i, raise_error=False):
    if i is None:
        return []
    else:
        return [int(j) for j in i]


class ChainExecutionConfigForm(Form):
    chain_id = SelectField("Chain", coerce=empty_or_integer, choices=[(c.chain_id, c.chain_id) for c in Model().get_all_chains()])
    task_id = SelectField("Task type", coerce=empty_or_integer)
    chain_name = StringField("Chain name", filters=[lambda i: i or None])
    run_at = StringField("Cron style schedule", filters=[lambda i: i or None])
    run_at_minute = SelectMultipleField("Run at minute", coerce=empty_or_integer, choices=[(i, i) for i in range(0,60, 5)], filters=[run_at_filter])
    run_at_hour = SelectMultipleField("Run at hour", coerce=empty_or_integer, choices=[(i, i) for i in range(0,24)], filters=[run_at_filter])
    run_at_day = SelectMultipleField("Run at day", coerce=empty_or_integer, choices=[(i, i) for i in range(0,31)], filters=[run_at_filter])
    run_at_month = SelectMultipleField("Run at month", coerce=empty_or_integer, choices=[(i, i) for i in range(1,13)], filters=[run_at_filter])
    run_at_day_of_week = SelectMultipleField("Run at day of week", coerce=empty_or_integer, choices=[(i, title) for i, title in enumerate(["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"])], filters=[run_at_filter])
    max_instances = StringField("max instances", widget=NumberInput(), filters=[lambda i: i or None])
    live = MyBooleanField("live")
    self_destruct = MyBooleanField("self destruct")
    exclusive_execution = MyBooleanField("Exclusive execution")
    excluded_execution_configs = StringField("excluded execution configs", filters=[lambda i: i or None])
    client_name = StringField("Client name", filters=[lambda i: i or None])

    def validate_chain_name(form, field):
        if field.data is None:
            raise ValidationError("Chain name must be set!")
        c = Model().get_chain_config_by_name(field.data)
        if hasattr(c, "chain_id") and c.chain_id != form.chain_id.data:
            raise ValidationError("Chain name must be unique!")

    def _validate_run_at(form, field):
        try:
            data = run_at_filter(field.data, True)
        except ValueError:
            raise StopValidation("Is not a number")
        field.data = data

    def validate_run_at_minute(form, field):
        form._validate_run_at(field)
        if isinstance(field.data, int):
            if field.data < 0 or field.data > 59:
                raise ValidationError("Run at minute must be between 0 and 59 or * if you want to run every minute")

    def validate_run_at_hour(form, field):
        form._validate_run_at(field)
        if isinstance(field.data, int):
            if field.data < 0 or field.data > 23:
                raise ValidationError("Run at hour must be between 0 and 23 or * if you want to run every hour")

    def validate_run_at_day(form, field):
        form._validate_run_at(field)
        if isinstance(field.data, int):
            if field.data < 1 or field.data > 31:
                raise ValidationError("Run at day must be between 1 and 31 or * if you want to run every day")

    def validate_run_at_month(form, field):
        form._validate_run_at(field)
        if isinstance(field.data, int):
            if field.data < 1 or field.data > 31:
                raise ValidationError("Run at month must be between 1 and 12 or * if you want to run every month")

    def validate_run_at_day_of_week(form, field):
        form._validate_run_at(field)
        if isinstance(field.data, int):
            if field.data < 0 or field.data > 7:
                raise ValidationError("Run at day of week must be between 0 and 7 or * if you want to run every day of week")

@app.route('/')
def index():
    db = Model()
    return render_template("dashboard.html", last_jobs=db.get_last_jobs(), next_jobs=db.get_next_jobs(), self_destructive_chains=db.get_self_destructive_chains())

@app.route('/tasks/add/', methods=["GET", "POST"])
def add_base_task():
    form = TaskForm(request.form)
    if request.method == 'POST' and form.validate():
        db = Model(task_id=None, task_name=form.task_name.data, task_function=form.task_function.data, task_kind=form.task_kind.data)
        db.save_task()
        return redirect(f"/chain_execution_config/", code=302)
    return render_template("edit_task.html", form=form)

@app.route('/tasks/')
def list_tasks():
    db = Model()
    return render_template("list_tasks.html", list=db.get_all_tasks())

@app.route('/task/<int:task_id>/')
def view_task(task_id):
    db = Model()
    obj = db.get_task_by_id(task_id)
    if obj is None:
        abort(404)
    return render_template("view_task.html", obj=obj)

@app.route('/task/<int:task_id>/edit/', methods=["GET", "POST"])
def edit_task(task_id):
    db = Model(task_id=task_id)
    obj = db.get_task_by_id(task_id)
    if obj is None:
        abort(404)
    form = TaskForm(request.form, obj=obj)
    if obj.task_kind == 'BUILTIN':
        form.task_kind.choices = [('BUILTIN', 'BUILTIN')]
        form.task_kind.render_kw = {'readonly': 'true'}
        form.task_name.render_kw = {'readonly': 'true'}
        form.task_function.render_kw = {'readonly': 'true'}
    if request.method == 'POST' and form.validate():
        db.update(task_name=form.task_name.data, task_function=form.task_function.data, task_kind=form.task_kind.data)
        db.save_task()
        return redirect(f"/task/{task_id}", code=302)
    return render_template("edit_task.html", form=form)

@app.route('/chain/<int:chain_execution_config>/<int:chain_id>/')
def view_chain(chain_id, chain_execution_config):
    db = Model(chain_id=chain_id, chain_execution_config=chain_execution_config)
    obj = db.get_chain_by_id(chain_id)
    if obj is None:
        abort(404)
    return render_template("view_chain.html", obj=obj)

@app.route('/chain/<int:chain_execution_config>/<int:chain_id>/edit/', methods=["GET", "POST"])
def edit_chain(chain_id, chain_execution_config):
    db = Model(chain_id=chain_id, chain_execution_config=chain_execution_config)
    obj = db.get_chain_by_id(chain_id)
    form = ChainForm(request.form, obj=obj)
    form.task_id.choices = [(t.task_id, f'{t.task_id}. {t.task_name}') for t in db.get_all_tasks()]
    form.database_connection.choices = [(d.database_connection, f'{d.database_connection}. {d.comment}') for d in Model().get_all_db_connections()] + [(None, "No special connection string")]
    if request.method == 'POST' and form.validate():
        db.update(task_id=form.task_id.data, run_uid=form.run_uid.data, database_connection=form.database_connection.data, ignore_error=form.ignore_error.data)
        db.save_chain()
        return redirect(f"/chain_execution_config/{chain_execution_config}/", code=302)
    return render_template("edit_chain.html", form=form)

@app.route('/chain/<int:chain_execution_config>/<int:parent_id>/add/', methods=["GET", "POST"])
def add_chain_to_parent(parent_id, chain_execution_config):
    if parent_id == 0:
        parent_id = None
    db = Model(parent_id=parent_id, chain_execution_config=chain_execution_config, chain_id=None)
    obj = db.get_chain_by_parent(parent_id)
    form = ChainForm(request.form, obj=obj)
    form.task_id.choices = [(t.task_id, f'{t.task_id}. {t.task_name}') for t in db.get_all_tasks()]
    form.database_connection.choices = [(d.database_connection, f'{d.database_connection}. {d.comment}') for d in Model().get_all_db_connections()] + [(None, "No special connection string")]
    if request.method == 'POST' and form.validate():
        db.update(task_id=form.task_id.data, run_uid=form.run_uid.data, database_connection=form.database_connection.data, ignore_error=form.ignore_error.data)
        db.save_chain()
        return redirect(f"/chain_execution_config/{chain_execution_config}/", code=302)
    return render_template("edit_chain.html", chains=db.chains_notparents(), tasks=db.get_all_tasks(), form=form)

@app.route('/chain/<int:chain_execution_config>/<int:chain_id>/delete/', methods=["GET", "POST"])
def delete_chain(chain_id, chain_execution_config):
    if request.method == 'GET':
        db = Model(chain_id=chain_id, chain_execution_config=chain_execution_config)
        obj = db.get_chain_by_id(chain_id)
        if obj is None:
            abort(404)
        return render_template("delete.html", obj=obj)
    else:
        db = Model(chain_id=chain_id)
        db.delete_chain()
        return redirect(f"/chain_execution_config/", code=302)


@app.route('/chain_execution_config/add/', methods=["GET", "POST"])
def add_chain_execution_configs():
    db = Model(chain_execution_config=None)
    form = ChainExecutionConfigForm(request.form)
    form.chain_id.choices = [(c.chain_id, c.chain_id) for c in db.get_all_chains()] + [(None, "Add new chain")]
    form.task_id.choices = [(t.task_id, f'{t.task_id}. {t.task_name}') for t in db.get_all_tasks()]
    if request.method == 'POST' and form.validate():

        if form.run_at.data != None:
            cron = form.run_at.data
        else:
            cron_run_at_minute = ",".join([str(t) for t in form.run_at_minute.data])             if len(form.run_at_minute.data)         > 0 else "*"
            cron_run_at_hour = ",".join([str(t) for t in form.run_at_hour.data])                 if len(form.run_at_hour.data)           > 0 else "*"
            cron_run_at_day = ",".join([str(t) for t in form.run_at_day.data])                   if len(form.run_at_day.data)            > 0 else "*"
            cron_run_at_month = ",".join([str(t) for t in form.run_at_month.data])               if len(form.run_at_month.data)          > 0 else "*"
            cron_run_at_day_of_week = ",".join([str(t) for t in form.run_at_day_of_week.data])   if len(form.run_at_day_of_week.data)    > 0 else "*"
            # CRON style
            cron = f"{cron_run_at_minute} {cron_run_at_hour} {cron_run_at_day} {cron_run_at_month} {cron_run_at_day_of_week}"

        cron_matrix = [[(x if x !='*' else None) for x in s.split(',')] for s in cron.split(' ')]
        for run_at_minute in cron_matrix[0]:
            for run_at_hour in cron_matrix[1]:
                for run_at_day in cron_matrix[2]:
                    for run_at_month in cron_matrix[3]:
                        for run_at_day_of_week in cron_matrix[4]:

                            db.update(chain_id=form.chain_id.data, task_id=form.task_id.data, chain_name=f"{form.chain_name.data}-{run_at_minute or '*'}_{run_at_hour or '*'}_{run_at_day or '*'}_{run_at_month or '*'}_{run_at_day_of_week or '*'}", run_at_minute=run_at_minute, run_at_hour=run_at_hour, run_at_day=run_at_day, run_at_month=run_at_month, run_at_day_of_week=run_at_day_of_week, max_instances=form.max_instances.data, live=form.live.data, self_destruct=form.self_destruct.data, exclusive_execution=form.exclusive_execution.data, excluded_execution_configs=form.excluded_execution_configs.data, client_name=form.client_name.data)
                            db.save_chain_config(commit=False)
        db.commit()
        return redirect(f"/chain_execution_config/", code=302)
    return render_template("edit_chain_execution_config.html", form=form)

@app.route('/chain_execution_config/')
def list_chain_execution_configs():
    db = Model()
    return render_template("list_chain_execution_configs.html", list=db.get_all_chain_configs())

@app.route('/chain_execution_config/<int:id>/')
def view_chain_execution_configs(id):
    db = Model(chain_execution_config=id)
    obj = db.get_chain_config_by_id(id)
    if obj is None:
        abort(404)
    return render_template("view_chain_execution_config.html", obj=obj)

@app.route('/chain_execution_config/<int:id>/edit/', methods=["GET", "POST"])
def edit_chain_execution_configs(id):
    db = Model(chain_execution_config=id)
    obj = db.get_chain_config_by_id(id)
    form = ChainExecutionConfigForm(request.form, obj=obj)
    form.task_id.choices = [(None, "")]
    if request.method == 'POST' and form.validate():

        suffix = re.compile('-[0-9*]+_[0-9*]+_[0-9*]+_[0-9*]+_[0-9*]+')
        chain_name = suffix.sub("", form.chain_name.data)
        if form.run_at.data != None:
            cron = form.run_at.data
        else:
            cron_run_at_minute = ",".join([str(t) for t in form.run_at_minute.data])             if len(form.run_at_minute.data)         > 0 else "*"
            cron_run_at_hour = ",".join([str(t) for t in form.run_at_hour.data])                 if len(form.run_at_hour.data)           > 0 else "*"
            cron_run_at_day = ",".join([str(t) for t in form.run_at_day.data])                   if len(form.run_at_day.data)            > 0 else "*"
            cron_run_at_month = ",".join([str(t) for t in form.run_at_month.data])               if len(form.run_at_month.data)          > 0 else "*"
            cron_run_at_day_of_week = ",".join([str(t) for t in form.run_at_day_of_week.data])   if len(form.run_at_day_of_week.data)    > 0 else "*"
            # CRON style
            cron = f"{cron_run_at_minute} {cron_run_at_hour} {cron_run_at_day} {cron_run_at_month} {cron_run_at_day_of_week}"

        cron_matrix = [[(x if x !='*' else None) for x in s.split(',')] for s in cron.split(' ')]
        for run_at_minute in cron_matrix[0]:
            for run_at_hour in cron_matrix[1]:
                for run_at_day in cron_matrix[2]:
                    for run_at_month in cron_matrix[3]:
                        for run_at_day_of_week in cron_matrix[4]:

                            db.update(chain_id=form.chain_id.data, task_id=form.task_id.data, chain_name=f"{chain_name}-{run_at_minute or '*'}_{run_at_hour or '*'}_{run_at_day or '*'}_{run_at_month or '*'}_{run_at_day_of_week or '*'}", run_at_minute=run_at_minute, run_at_hour=run_at_hour, run_at_day=run_at_day, run_at_month=run_at_month, run_at_day_of_week=run_at_day_of_week, max_instances=form.max_instances.data, live=form.live.data, self_destruct=form.self_destruct.data, exclusive_execution=form.exclusive_execution.data, excluded_execution_configs=form.excluded_execution_configs.data, client_name=form.client_name.data)
                            db.save_chain_config(commit=False)
        db.commit()
        return redirect(f"/chain_execution_config/{id}/", code=302)
    form.run_at_minute.process_data([obj.run_at_minute] if obj.run_at_minute is not None else [])
    form.run_at_hour.process_data([obj.run_at_hour] if obj.run_at_hour is not None else [])
    form.run_at_day.process_data([obj.run_at_day] if obj.run_at_day is not None else [])
    form.run_at_month.process_data([obj.run_at_month] if obj.run_at_month is not None else [])
    form.run_at_day_of_week.process_data([obj.run_at_day_of_week] if obj.run_at_day_of_week is not None else [])
    return render_template("edit_chain_execution_config.html", form=form)


@app.route('/chain_execution_parameters/<int:chain_execution_config>/<int:chain_id>/<int:order_id>/add/', methods=["GET", "POST"])
def create_chain_execution_parameters(chain_execution_config, chain_id, order_id):
    obj = Object(chain_execution_config=chain_execution_config, chain_id=chain_id, order_id=order_id)
    form = ChainExecutionParametersForm(request.form, obj=obj)
    if request.method == 'POST' and form.validate():
        db = Model(chain_execution_config=chain_execution_config, chain_id=chain_id, order_id=form.order_id.data, value=json.dumps(form.value.data))
        db.save_chain_parameter()
        return redirect(f"/chain_execution_config/{chain_execution_config}/", code=302)
    return render_template("edit_chain_execution_parameters.html", form=form)

@app.route('/chain_execution_parameters/<int:chain_execution_config>/<int:chain_id>/<int:order_id>/delete/', methods=["GET", "POST"])
def delete_chain_execution_parameters(chain_execution_config, chain_id, order_id):
    if request.method == 'GET':
        db = Model()
        obj = db.get_chain_parameter_by_id(chain_execution_config, chain_id, order_id)
        if obj is None:
            abort(404)
        return render_template("delete.html", obj=obj)
    else:
        db = Model(chain_execution_config=chain_execution_config, chain_id=chain_id, order_id=order_id)
        db.delete_chain_parameter()
        return redirect(f"/chain_execution_config/{chain_execution_config}/", code=302)

@app.route('/chain_execution_parameters/<int:chain_execution_config>/<int:chain_id>/<int:order_id>/')
def view_chain_execution_parameters(chain_execution_config, chain_id, order_id):
    db = Model()
    obj = db.get_chain_parameter_by_id(chain_execution_config, chain_id, order_id)
    if obj is None:
        abort(404)
    return render_template("view_chain_execution_parameters.html", obj=obj)

@app.route('/chain_execution_parameters/<int:chain_execution_config>/<int:chain_id>/<int:order_id>/edit/', methods=["GET", "POST"])
def edit_chain_execution_parameters(chain_execution_config, chain_id, order_id):
    db = Model(chain_execution_config=chain_execution_config, chain_id=chain_id, order_id=order_id)
    obj = db.get_chain_parameter_by_id(chain_execution_config, chain_id, order_id)
    form = ChainExecutionParametersForm(request.form, obj=obj)
    if request.method == 'POST' and form.validate():
        db.update(order_id=form.order_id.data, value=json.dumps(form.value.data))
        db.save_chain_parameter()
        return redirect(f"/chain_execution_config/{chain_execution_config}/", code=302)
    return render_template("edit_chain_execution_parameters.html", form=form)

@app.route('/execution_log/<int:id>/')
def view_execution_logs(id):
    db = Model(chain_execution_config=id)
    return render_template("view_execution_logs.html", list=db.get_execution_logs(id), chain_config=db.get_chain_config_by_id(id))

@app.route('/db_connections/')
def list_db_connections():
    db = Model()
    return render_template("list_db_connections.html", list=db.get_all_db_connections())

@app.route('/db_connections/add/', methods=["GET", "POST"])
def add_db_connection():
    form = DBConnectionForm(request.form)
    if request.method == 'POST' and form.validate():
        db = Model(database_connection=None, connect_string=form.connect_string.data, comment=form.comment.data)
        db.save_db_connection()
        return redirect(f"/db_connections/", code=302)
    return render_template("edit_db_connection.html", form=form)

@app.route('/db_connection/<int:database_connection>/edit/', methods=["GET", "POST"])
def edit_db_connection(database_connection):
    db = Model(database_connection=database_connection)
    obj = db.get_db_connection_by_id(database_connection)
    if obj is None:
        abort(404)
    form = DBConnectionForm(request.form, obj=obj)
    if request.method == 'POST' and form.validate():
        db.update(databse_connection=form.database_connection.data, connect_string=form.connect_string.data, comment=form.comment.data)
        db.save_db_connection()
        return redirect(f"/db_connection/{database_connection}/", code=302)
    return render_template("edit_db_connection.html", form=form)

@app.route('/db_connection/<int:database_connection>/')
def view_db_connection(database_connection):
    db = Model()
    obj = db.get_db_connection_by_id(database_connection)
    if obj is None:
        abort(404)
    return render_template("view_db_connection.html", obj=obj)

@app.errorhandler(404)
def page_not_found(error):
   return render_template('404.html', error=error), 404
