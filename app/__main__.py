import asyncio

import uvicorn


if __name__ == "__main__":
    config = uvicorn.Config("app.main:create_app", factory=True)
    with asyncio.Runner(loop_factory=asyncio.SelectorEventLoop) as runner:
        runner.run(uvicorn.Server(config).serve())
