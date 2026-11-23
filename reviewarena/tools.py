import json,sys,os
from contextlib import asynccontextmanager
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from .kb import ROOT

@asynccontextmanager
async def connect(name,logs,snapshot=None):
    snapshot=str(snapshot) if snapshot is not None else os.environ.get('REVIEWARENA_KB_SNAPSHOT')
    server=StdioServerParameters(env={'REVIEWARENA_KB_SNAPSHOT':snapshot} if snapshot else None,command=sys.executable,args=[str(ROOT/f'mcp_{name}_server.py')])
    async with stdio_client(server) as streams, ClientSession(*streams) as session:
        await session.initialize()
        async def call(tool,**args):
            result=await session.call_tool(tool,args)
            logs.append({'server':name,'tool':tool,'arguments':args,'ok':not result.isError})
            if result.isError:raise RuntimeError(str(result.content))
            if result.structuredContent is not None:
                data=result.structuredContent
                return data.get('result',data)
            return [json.loads(item.text) for item in result.content]
        yield call
