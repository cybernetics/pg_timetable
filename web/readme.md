This is a flask application to manage pg_timetable from web inteface.

# Local install

To run it you need to install requirements:

    pip install -r requirements.txt

define required variables

    export FLASK_APP=server.py
    export PG_TIMETABLE_DBNAME=postgres
    export PG_TIMETABLE_USER=postgres
    export PG_TIMETABLE_HOST=127.0.0.1
    export PG_TIMETABLE_PASSWORD=password

and start the service

    flask run

# Docker install

    podman build . -t pg_timetable_gui:latest
    podman run --rm -e "PG_TIMETABLE_HOST=127.0.0.1" -e "PG_TIMETABLE_PASSWORD=password" -e --network="host" localhost/pg_timetable_gui:latest

Open http://127.0.0.1:5000 in your favorite browser.

Create base task on page http://127.0.0.1:5000/tasks/add/

Create chain ececution config on page http://127.0.0.1:5000/chain_execution_config/add/

On page http://127.0.0.1:5000/chain_execution_config/ you can see the config and you will see the links to edit it.

Some TODO:
 * On chain parameters page, if you want to add a string as a parameter you need to quote it, if you need to add an integer keep it unquoted.





