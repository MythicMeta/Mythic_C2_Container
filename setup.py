import pathlib
from setuptools import setup

# The directory containing this file
HERE = pathlib.Path(__file__).parent

# The text of the README file
README = (HERE / "README.md").read_text()

# This call to setup() does all the work
setup(
    name="mythic_c2_container",
    version="0.0.17",
    description="Functionality for Mythic C2 Containers",
    long_description=README,
    long_description_content_type="text/markdown",
    url="https://docs.mythic-c2.net/customizing/c2-related-development",
    author="@its_a_feature_",
    author_email="",
    license="BSD3",
    classifiers=[
        "License :: Other/Proprietary License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.7",
    ],
    packages=["mythic_c2_container"],
    include_package_data=True,
    install_requires=["aio_pika"],
    entry_points={
    },
)
