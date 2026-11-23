from mcp.server.fastmcp import FastMCP
from reviewarena import kb
server=FastMCP("ReviewKB")
@server.tool()
def search_triggers(query:str,claim_type:str="",k:int=20,paper_type:str="")->list:
    return kb.search(query,min(max(1,k),25),claim_type=claim_type,paper_type=paper_type)
@server.tool()
def similar_context(query:str,k:int=5)->list:
    return kb.similar_papers(query,min(max(1,k),10))
@server.tool()
def search_critiques(query:str,k:int=5,require_reply:bool=False)->list:
    return kb.search(query,min(max(1,k),10),'critique_text',require_reply=require_reply)
@server.tool()
def critique_stats()->list:
    return kb.stats()
if __name__=='__main__':server.run()
