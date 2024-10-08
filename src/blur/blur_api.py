import gc
import json

from fastapi import FastAPI, HTTPException, Response, UploadFile

from . import blur

MICROSERVICE = True

app = FastAPI()
print("API is preparing to start...")


@app.get("/")
async def root():
	return {"message": "GeoVisio 'Speedy Gonzales' Blurring API"}


@app.post(
	"/blur/",
	responses = {200: {"content": {"image/jpeg": {}}}},
	response_class=Response
)
async def blur_picture(picture: UploadFile, keep: str | None = '0'):
	blurredPic, blurInfo = blur.blurPicture(picture.file.read(), keep, MICROSERVICE)

	# For some reason garbage collection does not run automatically after
	# a call to an AI model, so it must be done explicitely
	gc.collect()

	if not blurredPic:
		raise HTTPException(status_code=400, detail="Invalid picture to process")

	headers = { "x-sgblur": json.dumps(blurInfo)}
	return Response(content=blurredPic, media_type="image/jpeg", headers=headers)


@app.get(
	"/blur/",
	responses={200: {"content": {"text/html": {}}}},
	response_class=Response
)
async def blur_form():
	return Response(content=open('demo.html', 'rb').read(), media_type="text/html")


@app.head(
	"/blur/",
	responses={200: {"content": {"text/html": {}}}},
	response_class=Response
)
async def blur_form():
	return


@app.post(
	"/deblur/",
	responses={200: {"content": {"image/jpeg": {}}}},
	response_class=Response
)
async def deblur_picture(picture: UploadFile, idx: int, salt=''):
	deblurredPic = blur.deblurPicture(picture, idx, salt)

	# For some reason garbage collection does not run automatically after
	# a call to an AI model, so it must be done explicitely
	gc.collect()

	if not deblurredPic:
		raise HTTPException(status_code=400, detail="Invalid picture to process")

	return Response(content=deblurredPic, media_type="image/jpeg")
