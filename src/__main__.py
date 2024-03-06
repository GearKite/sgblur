from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path
from time import perf_counter

import typer
from PIL import Image
from rich import print

from .blur import blur

app = typer.Typer(help="GeoVisio blurring scripts")


@contextmanager
def log_elapsed(ctx: str):
    """Context manager used to log the elapsed time of the context

    Args:
        ctx (str): Label to describe what is timed
    """

    start = perf_counter()
    yield
    print(f"⏲ [bold]{ctx}[/bold] done in {timedelta(seconds=perf_counter()-start)}")


@app.callback()
def main(
    input_file: Path = typer.Argument(..., help="Picture to blur"),
    output_file: Path = typer.Argument(..., help="Output file path"),
    # strategy: Strategy = typer.Option(Strategy.fast, help="Blur algorithm to use"),
    mask: bool = typer.Option(
        False, "--mask/--picture", help="Get a blur mask instead of blurred picture"
    ),
) -> None:
    """Creates a blurred version of a picture"""

    with log_elapsed("Reading image"):
        with open(input_file, "rb") as f:
            input_bytes = f.read()

    if mask:
        with log_elapsed("Creating mask"):
            input_pil = Image.open(input_file)
            mask = blur.create_mask(input_bytes, input_pil)

        with log_elapsed("Saving mask"):
            mask.save(output_file)
    else:
        with log_elapsed("Blurring picture"):
            image, _ = blur.blurPicture(input_bytes, None, False)

        with log_elapsed("Saving blurred image"):
            with open(output_file, "wb+") as f:
                f.write(image)


if __name__ == "__main__":
    typer.run(main)
