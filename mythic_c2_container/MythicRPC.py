from aio_pika import connect_robust, IncomingMessage, Message
from aio_pika.patterns import RPC
import asyncio
import uuid
import json
import base64
import pathlib
import sys
from .config import settings
from enum import Enum

c2_connection = None
rpc = None
c2_callback_queue = None
c2_channel = None
c2_loop = None
c2_futures = {}


class RPCStatus(Enum):
    Success = "success"
    Error = "error"

class RPCResponse:
    def __init__(self, resp: dict = None):
        if resp is None:
            self.status = RPCStatus.Success
            self.error = None
            self.response = ""
            self._raw_resp = ""
        else:
            self._raw_resp = resp
            if resp["status"] == "success":
                self.status = RPCStatus.Success
                self.response = resp["response"] if "response" in resp else None
                self.error = None
            else:
                self.status = RPCStatus.Error
                self.error = resp["error"]
                self.response = resp["response"] if "response" in resp else None

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, status):
        self._status = status

    @property
    def error(self):
        return self._error

    @error.setter
    def error(self, error):
        self._error = error

    @property
    def response(self):
        return self._response

    @response.setter
    def response(self, response):
        self._response = response

    def to_json(self):
        return {"status": self.status.value, "response": self.response}

    def __str__(self):
        return json.dumps(self._raw_resp)


class MythicBaseRPC:
    async def connect(self):
        global c2_connection
        global rpc
        global c2_callback_queue
        global c2_channel
        global c2_loop
        if c2_connection is None:
            c2_connection = await connect_robust(
                host=settings.get("host", "127.0.0.1"),
                login=settings.get("username", "mythic_user"),
                password=settings.get("password", "mythic_password"),
                virtualhost=settings.get("virtual_host", "mythic_vhost"),       
            )
            c2_channel = await c2_connection.channel()
            c2_callback_queue = await c2_channel.declare_queue(exclusive=True)
            c2_loop = asyncio.get_event_loop()
            await c2_callback_queue.consume(self.on_response)
            try:
                rpc = await RPC.create(c2_channel)
            except Exception as e:
                print("Failed to create rpc\n" + str(e))
                sys.stdout.flush()
        return self

    def on_response(self, message: IncomingMessage):
        global c2_futures
        future = c2_futures.pop(message.correlation_id)
        future.set_result(message.body)


class MythicRPC(MythicBaseRPC):
    async def get_functions(self) -> RPCResponse:
        global rpc
        await self.connect()
        try:
            output = await rpc.proxy.get_rpc_functions()
            return RPCResponse(output)
        except Exception as e:
            print(str(sys.exc_info()[-1].tb_lineno) +str(e))
            sys.stdout.flush()
            return RPCResponse({"status": "error", "error": "Failed to find function and call it in RPC, does it exist?\n" + str(e)})

    async def execute(self, function_name: str, **func_kwargs) -> RPCResponse:
        global rpc
        await self.connect()
        try:
            func = getattr(rpc.proxy, function_name)
            if func is not None and callable(func):
                output = await func(**func_kwargs)
            else:
                output = await rpc.call(function_name, kwargs=dict(**func_kwargs))
            return RPCResponse(output)
        except Exception as e:
            print(str(sys.exc_info()[-1].tb_lineno) + " " + str(e))
            sys.stdout.flush()
            return RPCResponse({"status": "error", "error": "Failed to call function:\n" + str(e)})

    async def call_c2rpc(self, n, receiver: str = None) -> RPCResponse:
        global c2_callback_queue
        global c2_channel
        global c2_loop
        global c2_futures
        await self.connect()
        correlation_id = str(uuid.uuid4())
        future = c2_loop.create_future()

        c2_futures[correlation_id] = future
        router = "{}_rpc_queue".format(receiver)
        await c2_channel.default_exchange.publish(
            Message(
                json.dumps(n).encode(),
                content_type="application/json",
                correlation_id=correlation_id,
                reply_to=c2_callback_queue.name,
            ),
            routing_key=router,
        )
        return RPCResponse(json.loads(await future))


    async def execute_c2rpc(self, c2_profile: str, function_name: str, message: str, task_id: int) -> RPCResponse:
        try:
            resp = await self.call_c2rpc(
                {"action": function_name,
                 "message": message,
                 "task_id": task_id
                 },
                c2_profile)
            return resp

        except Exception as e:
            print(str(sys.exc_info()[-1].tb_lineno) + " " + str(e))
            sys.stdout.flush()
            return RPCResponse({"status": "error", "error": "Failed to call function:\n" + str(e)})
