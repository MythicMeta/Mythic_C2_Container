from . import MythicBaseRPC
import base64


class MythicRPCResponse(MythicBaseRPC.RPCResponse):
    def __init__(self, resp: MythicBaseRPC.RPCResponse):
        super().__init__(resp._raw_resp)
        if resp.status == MythicBaseRPC.MythicStatus.Success:
            self.data = resp.response
        else:
            self.data = None

    @property
    def data(self):
        return self._data

    @data.setter
    def data(self, data):
        self._data = data


class MythicCallbackRPC(MythicBaseRPC.MythicBaseRPC):

    async def add_event_message(
        self, message: str, level: str = "info"
    ) -> MythicRPCResponse:
        resp = await self.call(
            {"action": "add_event_message", "level": level, "message": message}
        )
        return MythicRPCResponse(resp)

