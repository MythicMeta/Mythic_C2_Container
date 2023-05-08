#!/usr/bin/env python3
import aio_pika
import os
import time
import sys
import subprocess
import _thread
import base64
import json
import socket
import asyncio
import pathlib
import traceback
from . import C2ProfileBase
from importlib import import_module, invalidate_caches
from functools import partial
from .config import settings
import glob
import psutil

credentials = None
connection_params = None
running = False
process = None
thread = None
hostname = ""
output = ""
exchange = None
container_files_path = None

container_version = "4"
pypi_version = "0.0.31"


def kill(proc_pid):
    target_processes = psutil.Process(proc_pid)
    for proc in target_processes.children(recursive=True):
        proc.kill()
    target_processes.kill()


def deal_with_stdout():
    global process
    global output
    while True:
        try:
            for line in iter(process.stdout.readline, b""):
                output += line.decode("utf-8")
        except Exception as e:
            print_flush("[-] Exiting thread due to: {}\n".format(str(e)))
            break


def import_all_c2_functions():
    import glob

    # Get file paths of all modules.
    modules = glob.glob("c2_functions/*.py")
    invalidate_caches()
    try:
        for x in modules:
            if not x.endswith("__init__.py") and x[-3:] == ".py":
                module = import_module(
                    "c2_functions." + pathlib.Path(x).stem, package=None
                )
                for el in dir(module):
                    if "__" not in el:
                        globals()[el] = getattr(module, el)
    except Exception as e:
        print_flush("[-] Failed to parse c2_functions code:\n" + str(e))
        sys.exit(1)


async def send_status(message="", routing_key=""):
    global exchange
    try:
        message_body = aio_pika.Message(message.encode())
        await exchange.publish(message_body, routing_key=routing_key)
    except Exception as e:
        print_flush("[-] Exception in send_status: {}".format(str(e)))


async def callback(message: aio_pika.IncomingMessage):
    global running
    global process
    global output
    global thread
    global hostname
    global container_files_path
    with message.process():
        # messages of the form: c2.modify.PROFILE NAME.command
        try:
            command = message.routing_key.split(".")[3]
            username = message.routing_key.split(".")[4]
            # command = body.decode('utf-8')
            if command == "sync_classes":
                try:
                    import_all_c2_functions()
                    # c2profile = {}
                    for cls in C2ProfileBase.C2Profile.__subclasses__():
                        c2profile = cls().to_json()
                        break
                    await send_status(
                        message=json.dumps(c2profile),
                        routing_key="c2.status.{}.{}.sync_classes.{}.{}".format(
                            hostname,
                            "running" if running else "stopped",
                            username,
                            container_version,
                        ),
                    )
                except Exception as e:
                    await send_status(
                        message='{"message": "Error while syncing info: {}"}'.format(
                            str(traceback.format_exc())
                        ),
                        routing_key="c2.status.{}.{}.sync_classes.{}.{}".format(
                            hostname,
                            "running" if running else "stopped",
                            username,
                            container_version,
                        ),
                    )
            else:
                print("Unknown command: {}".format(command))
                sys.stdout.flush()
        except Exception as e:
            print(
                "[-] Failed overall message processing: "
                + str(sys.exc_info()[-1].tb_lineno)
                + " "
                + str(e)
            )
            sys.stdout.flush()


async def get_status(request):
    global running
    global process
    global output
    output_message = {}
    if process.poll() is None:
        running = True
    else:
        running = False
        try:
            process.kill()
        except Exception as e:
            pass
    output_message = {
        "running": running,
        "output": output,
        "status": "success",
        "version": container_version,
    }
    output = ""
    return output_message


async def start_profile(request):
    global running
    global process
    global thread
    global output
    global container_files_path
    try:
        server_option_path = container_files_path / "server*"
        server_options = glob.glob(str(server_option_path))
        # print(server_options)
        if len(server_options) == 0:
            print_flush(
                f"[-] no files that start with '{server_option_path}' in the name in the c2_code directory"
            )
            running = False
            output_message = {
                "status": "error",
                "running": False,
                "error": "Failed to find server file",
            }
            return output_message
        else:
            server_path = server_options[0]
        # server_path = container_files_path / "server"
        print(f"[*] c2 server path: {server_path}")
        output_message = {}
        if not running:
            os.chmod(server_path, mode=0o777)
            output = ""
            process = subprocess.Popen(
                str(server_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(container_files_path),
                shell=True,
            )
            thread = _thread.start_new_thread(deal_with_stdout, ())
            time.sleep(3)
            process.poll()
            if process.returncode is not None:
                # this means something went wrong and the process is dead
                running = False
                output_message = {
                    "status": "success",
                    "running": running,
                    "output": "Failed to start\nOutput: {}".format(output),
                    "version": container_version,
                }
                output = ""
            else:
                running = True
                output_message = {
                    "status": "success",
                    "running": running,
                    "output": "Started with pid: {}...\nOutput: {}".format(
                        str(process.pid), output
                    ),
                    "version": container_version,
                }
                output = ""
        else:
            output_message = {
                "status": "success",
                "running": running,
                "output": "Already running...\nOutput: {}".format(output),
                "version": container_version,
            }
            output = ""
        return output_message
    except Exception as e:
        print_flush(
            "Exception trying to send message back to container for start_profile! "
            + str(sys.exc_info()[-1].tb_lineno)
            + " "
            + str(e)
        )


async def stop_profile(request):
    global running
    global process
    global thread
    global output
    output_message = {}
    try:
        if running:
            try:
                # print("trying to kill")
                # process.kill()
                kill(process.pid)
                # print("killed, trying to communicate")
                process.communicate(timeout=3)
                # print("communicated")
            except Exception as e:
                print(f"[-] hit exception during subprocess kill: {e}")
                sys.stdout.flush()
                pass
            running = False
            output_message = {
                "status": "success",
                "output": "Process killed...\nOld Output: {}".format(output),
                "running": running,
                "version": container_version,
            }
            output = ""
        else:
            output_message = {
                "status": "success",
                "running": running,
                "output": "Process not running...\nOld Output: {}".format(output),
                "version": container_version,
            }
            output = ""
        return output_message
    except Exception as e:
        print_flush(
            "[-] Exception trying to send message back to container for stop_profile! "
            + str(sys.exc_info()[-1].tb_lineno)
            + " "
            + str(e)
        )


async def sync_classes():
    global running
    try:
        import_all_c2_functions()
        c2profile = {}
        for cls in C2ProfileBase.C2Profile.__subclasses__():
            c2profile = cls().to_json()
            break
        await send_status(
            message=json.dumps(c2profile),
            routing_key="c2.status.{}.{}.sync_classes.{}.{}".format(
                hostname, "running" if running else "stopped", "", container_version
            ),
        )
    except Exception as e:
        print_flush(
            "[-] Exception trying to send message back to container for sync_classes! "
            + str(sys.exc_info()[-1].tb_lineno)
            + " "
            + str(e)
        )
        await send_status(
            message='{"message": "Error while syncing info: {}"}'.format(
                str(traceback.format_exc())
            ),
            routing_key="c2.status.{}.{}.sync_classes.{}.{}".format(
                hostname, "running" if running else "stopped", "", container_version
            ),
        )


async def get_file(request):
    global container_files_path
    global running
    try:
        path = container_files_path / request["filename"]
        file_data = open(path, "rb").read()
    except Exception as e:
        file_data = b"File not found"
    return {
        "status": "success",
        "running": running,
        "filename": str(path),
        "data": base64.b64encode(file_data).decode("utf-8"),
        "version": container_version,
    }


async def exit_container(request):
    print_flush("[-] Container tasked to exit...")
    sys.exit(1)


async def write_file(request):
    global container_files_path
    global running
    try:
        file_path = container_files_path / request["file_path"]
        file_path = file_path.resolve()
        if container_files_path not in file_path.parents:
            response = {
                "status": "error",
                "error": "trying to break out of path",
                "running": running,
                "version": container_version,
            }
        else:
            file = open(file_path, "wb")
            file.write(base64.b64decode(request["data"]))
            file.close()
            response = {
                "status": "success",
                "filename": str(file_path),
                "running": running,
                "version": container_version,
            }
    except Exception as e:
        response = {
            "status": "error",
            "error": str(e),
            "running": running,
            "version": container_version,
        }
    return response


def print_flush(message: str):
    print(message)
    sys.stdout.flush()


async def rabbit_c2_rpc_callback(
    exchange: aio_pika.Exchange, message: aio_pika.IncomingMessage
):
    try:
        with message.process():
            request = json.loads(message.body.decode())
            if "action" in request:
                response = await globals()[request["action"]](request)
                response = json.dumps(response.to_json()).encode()
            else:
                response = json.dumps(
                    {"status": "error", "error": "Missing action"}
                ).encode()
            try:
                await exchange.publish(
                    aio_pika.Message(
                        body=response, correlation_id=message.correlation_id
                    ),
                    routing_key=message.reply_to,
                )
            except Exception as e:
                print_flush(
                    "[-] Exception trying to send message back to container for rpc! "
                    + str(sys.exc_info()[-1].tb_lineno)
                    + " "
                    + str(e)
                )
    except Exception as d:
        print_flush(
            f"[-] Failed to process message in rabbit_c2_rpc_callback: {str(sys.exc_info()[-1].tb_lineno)} {str(d)} "
        )


async def connect_and_consume_rpc(debug):
    connection = None
    global hostname
    while connection is None:
        try:
            if debug:
                print_flush(
                    f"[*] C2RPCTasking Step 1/3: Connecting to rabbitmq in connect_and_consume_rpc with c2 {hostname}"
                )
            connection = await aio_pika.connect_robust(
                host=settings.get("host", "127.0.0.1"),
                login=settings.get("username", "mythic_user"),
                password=settings.get("password", "mythic_password"),
                virtualhost="mythic_vhost",
            )
            if debug:
                print_flush(
                    f"[+] C2RPCTasking Step 1/3 Done: Successfully connected in connect_and_consume_rpc with c2 {hostname}"
                )
        except (ConnectionError, ConnectionRefusedError) as c:
            print_flush(
                "[-] C2RPCTasking Step 1/3 Error: Connection to rabbitmq failed, trying again..."
            )
        except Exception as e:
            print_flush(
                "[-] C2RPCTasking Step 1/3 Error: Exception in connect_and_consume_rpc connect: {}\n trying again...".format(
                    str(e)
                )
            )
        await asyncio.sleep(5)
    channel = await connection.channel()
    # get a random queue that only the apfell server will use to listen on to catch all heartbeats
    if debug:
        print_flush(
            "[*] C2RPCTasking Step 2/3: Declaring container specific rpc queue in connect_and_consume_rpc"
        )
    queue = await channel.declare_queue(
        "{}_rpc_queue".format(hostname), auto_delete=True
    )
    if debug:
        print_flush(
            f"[+] C2RPCTasking Step 2/3 Done: Successfully declared container specific rpc queue in connect_and_consume_rpc with c2 {hostname}"
        )
    await channel.set_qos(prefetch_count=10)
    try:
        if debug:
            print_flush(
                f"[*] C2RPCTasking Step 3/3: Starting to consume callbacks in connect_and_consume_rpc with c2 {hostname}"
            )
        if debug:
            print_flush(
                "[*] MythicService Step 4/5 Done: Created task for connect_and_consume_rpc from mythic_service"
            )
        await queue.consume(partial(rabbit_c2_rpc_callback, channel.default_exchange))
    except Exception as e:
        print_flush(
            "[-] C2RPCTasking Step 3/3 Error: Exception in connect_and_consume_rpc .consume: {}".format(
                str(sys.exc_info()[-1].tb_lineno) + " " + str(e)
            )
        )


async def rabbit_mythic_c2_rpc_callback(
    exchange: aio_pika.Exchange, message: aio_pika.IncomingMessage
):
    with message.process():
        try:
            request = json.loads(message.body.decode())
            response = await globals()[request["action"]](request)
        except Exception as e:
            print_flush(
                f"[-] Failed to process message in rabbit_mythic_c2_rpc_callback"
            )
            response = {"status": "error", "error": str(e)}
        try:
            await exchange.publish(
                aio_pika.Message(
                    body=json.dumps(response).encode(),
                    correlation_id=message.correlation_id,
                ),
                routing_key=message.reply_to,
            )
        except Exception as e:
            print_flush(
                "[-] Exception trying to send message back to container for rpc! "
                + str(sys.exc_info()[-1].tb_lineno)
                + " "
                + str(e)
            )


async def connect_and_consume_mythic_rpc(debug):
    connection = None
    global hostname
    while connection is None:
        try:
            if debug:
                print_flush(
                    f"[*] MythicRPCTasking Step 1/3: Connecting to rabbitmq in connect_and_consume_mythic_rpc with c2 {hostname}"
                )
            connection = await aio_pika.connect_robust(
                host=settings.get("host", "127.0.0.1"),
                login=settings.get("username", "mythic_user"),
                password=settings.get("password", "mythic_password"),
                virtualhost="mythic_vhost",
            )
            if debug:
                print_flush(
                    f"[+] MythicRPCTasking Step 1/3 Done: Successfully connected in connect_and_consume_mythic_rpc with c2 {hostname}"
                )
        except (ConnectionError, ConnectionRefusedError) as c:
            print_flush(
                "[-] MythicRPCTasking Step 1/3 Error: Connection to rabbitmq failed, trying again..."
            )
        except Exception as e:
            print_flush(
                "[-] MythicRPCTasking Step 1/3 Error: Exception in connect_and_consume_mythic_rpc connect: {}\n trying again...".format(
                    str(e)
                )
            )
        await asyncio.sleep(5)
    channel = await connection.channel()
    # get a random queue that only the apfell server will use to listen on to catch all heartbeats
    if debug:
        print_flush(
            f"[*] MythicRPCTasking Step 2/3: Declaring container specific mythic rpc queue in connect_and_consume_mythic_rpc with c2 {hostname}"
        )
    queue = await channel.declare_queue(
        "{}_mythic_rpc_queue".format(hostname), auto_delete=True
    )
    await channel.set_qos(prefetch_count=10)
    if debug:
        print_flush(
            f"[+] MythicRPCTasking Step 2/3 Done: Declared container specific mythic rpc queue in connect_and_consume_mythic_rpc with c2 {hostname}"
        )
    try:
        if debug:
            print_flush(
                f"[*] MythicRPCTasking Step 3/3: Starting to consume callbacks in connect_and_consume_mythic_rpc with c2 {hostname}"
            )
        task = await queue.consume(
            partial(rabbit_mythic_c2_rpc_callback, channel.default_exchange)
        )
        if debug:
            print_flush(
                f"[+] MythicRPCTasking Step 3/3 Done: Started to consume callbacks in connect_and_consume_mythic_rpc with c2 {hostname}"
            )
        if debug:
            print_flush(
                "[*] MythicService Step 5/5 Done: Created task for connect_and_consume_mythic_rpc from mythic_service"
            )
        # wait to sync classes with mythic until we have a way to get messages back
        await sync_classes()
    except Exception as e:
        print_flush(
            "[-] MythicRPCTasking Step 3/3 Error: Exception in connect_and_consume_mythic_rpc .consume: {}".format(
                str(sys.exc_info()[-1].tb_lineno) + " " + str(e)
            )
        )


async def mythic_service(debug: bool):
    global hostname
    global exchange
    global container_files_path
    connection = None
    container_files_path = pathlib.Path(
        os.path.abspath(os.path.dirname(sys.argv[0]))
    ).parent
    print_flush(f"[*] Importing C2 Profile information")
    import_all_c2_functions()
    for cls in C2ProfileBase.C2Profile.__subclasses__():
        hostname = cls().name
        break
    print_flush(f"[*] MythicService: Setting c2 name to {hostname}")
    if debug:
        print_flush(
            f"[*] MythicService: Setting the absolute path to the c2's folder as: {container_files_path}"
        )
    container_files_path = container_files_path / "c2_code"
    while connection is None:
        try:
            if debug:
                print_flush(
                    "[*] MythicService Step 1/5: Connecting to rabbitmq from mythic_service"
                )
            connection = await aio_pika.connect_robust(
                host=settings.get("host", "127.0.0.1"),
                login=settings.get("username", "mythic_user"),
                password=settings.get("password", "mythic_password"),
                virtualhost="mythic_vhost",
            )
            if debug:
                print_flush(
                    "[+] MythicService Step 1/5 Done: Successfully connected to rabbitmq from mythic_service"
                )
        except (ConnectionError, ConnectionRefusedError) as c:
            print_flush(
                "[-] MythicService Step 1/5 Error: Connection to rabbitmq failed, trying again..."
            )
        except Exception as e:
            print_flush(
                "[-] MythicService Step 1/5 Error: Exception in mythic_service: "
                + str(traceback.format_exc())
            )
        await asyncio.sleep(5)
    try:
        channel = await connection.channel()
        if debug:
            print_flush(
                "[*] MythicService Step 2/5: Declaring exchange in mythic_service"
            )
        exchange = await channel.declare_exchange(
            "mythic_traffic", aio_pika.ExchangeType.TOPIC
        )
        if debug:
            print_flush(
                "[+] MythicService Step 2/5 Done: Successfully declared queue in mythic_service"
            )
        queue = await channel.declare_queue("", exclusive=True)
        await queue.bind(
            exchange="mythic_traffic", routing_key="c2.modify.{}.#".format(hostname)
        )
        # just want to handle one message at a time so we can clean up and be ready
        await channel.set_qos(prefetch_count=30)
        if debug:
            print_flush(
                "[*] MythicService Step 3/5: Creating task to consume in mythic_service"
            )
        task = queue.consume(callback)
        if debug:
            print_flush(
                "[+] MythicService Step 3/5 Done: Successfully created task to consume in mythic_service"
            )
        if debug:
            print_flush(
                "[*] MythicService Step 4/5: Creating task for connect_and_consume_rpc from mythic_service"
            )
        task4 = asyncio.ensure_future(connect_and_consume_rpc(debug))

        if debug:
            print_flush(
                "[*] MythicService Step 5/5: Creating task for connect_and_consume_mythic_rpc from mythic_service"
            )
        task5 = asyncio.ensure_future(connect_and_consume_mythic_rpc(debug))
        if debug:
            print_flush(
                "[*] MythicService Step 5/5: Created task for connect_and_consume_mythic_rpc from mythic_service"
            )
        print(
            "[+] MythicService Listening for RabbitMQ Tasks from Mythic".format(
                hostname
            )
        )
        if debug:
            print_flush(
                "[*] MythicService Waiting for all tasks to finish in mythic_service"
            )
        result = await asyncio.gather(task, task4, task5)
    except Exception as e:
        print_flush(
            "[-] MythicService Exception in mythic_service: "
            + str(traceback.format_exc())
        )


async def heartbeat_loop(debug: bool):
    connection = None
    import_all_c2_functions()
    for cls in C2ProfileBase.C2Profile.__subclasses__():
        hostname = cls().name
        break
    while connection is None:
        try:
            if debug:
                print_flush(
                    "[*] Heartbeats Step 1/2: Connecting to rabbitmq from heartbeat_loop"
                )
            connection = await aio_pika.connect_robust(
                host=settings.get("host", "127.0.0.1"),
                login=settings.get("username", "mythic_user"),
                password=settings.get("password", "mythic_password"),
                virtualhost="mythic_vhost",
            )
            if debug:
                print_flush(
                    "[+] Heartbeats Step 1/2 Done: Successfully connected to rabbitmq from heartbeat_loop"
                )
            channel = await connection.channel()
            if debug:
                print_flush(
                    "[*] Heartbeats Step 2/2: Declaring exchange in heartbeat_loop for channel"
                )
            exchange = await channel.declare_exchange(
                "mythic_traffic", aio_pika.ExchangeType.TOPIC
            )
            if debug:
                print_flush(
                    "[+] Heartbeats Step 2/2 Done: Declared exchange in heartbeat_loop for channel"
                )
        except (ConnectionError, ConnectionRefusedError) as c:
            print_flush(
                "[-] Heartbeats Step 2/2 Error: Connection to rabbitmq failed, trying again..."
            )
            await asyncio.sleep(5)
            continue
        except Exception as e:
            print_flush(
                "[-] Heartbeats Step 2/2 Error: Exception in heartbeat_loop: "
                + str(traceback.format_exc())
            )
            await asyncio.sleep(5)
            continue
        while True:
            try:
                # routing key is ignored for fanout, it'll go to anybody that's listening, which will only be the server
                if debug:
                    print_flush("[*] Heartbeats Sending heartbeat in heartbeat_loop")
                await exchange.publish(
                    aio_pika.Message("heartbeat".encode()),
                    routing_key="c2.heartbeat.{}".format(hostname),
                )
                await asyncio.sleep(10)
            except Exception as e:
                print_flush(
                    "[-] Heartbeats Exception in heartbeat_loop trying to send heartbeat: "
                    + str(sys.exc_info()[-1].tb_lineno)
                    + " "
                    + str(e)
                )
                # if we get an exception here, break out to the bigger loop and try to connect again
                break


# start our service
def start_service_and_heartbeat(debug: bool = False):
    loop = asyncio.get_event_loop()
    get_version_info()
    asyncio.gather(mythic_service(debug), heartbeat_loop(debug))
    loop.run_forever()


def get_version_info():
    print_flush("[*] Mythic C2 Profile Version: " + container_version)
    print_flush("[*] Mythic C2 Profile PyPi Version: " + pypi_version)
