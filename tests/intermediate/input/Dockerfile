FROM python:3.12
WORKDIR /usr/src/app
RUN pip install git+https://github.com/indicio-tech/acapy-minimal-example.git@main
ADD populate_db.py .
ADD populate_mt_db.py .
ENTRYPOINT ["python"]
