import gc
import json

from fastapi import FastAPI, HTTPException, Response, UploadFile

from . import detect

app = FastAPI()
print("API is preparing to start...")


@app.get("/")
async def root():
	return {"message": "GeoVisio 'Speedy Gonzales' Face/Plate detection API"}

@app.post(
	"/detect/",
	responses = {200: {"content": {"application/json": {}}}},
	response_class=Response
)
async def detect_api(picture:UploadFile, cls:str = ''):
	result = detect.detector(picture.file.read(), cls)

	# For some reason garbage collection does not run automatically after
	# a call to an AI model, so it must be done explicitely
	gc.collect()

	if not result:
		raise HTTPException(status_code=400, detail="Couldn't process picture")

	return Response(content=json.dumps(result), media_type="application/json")
