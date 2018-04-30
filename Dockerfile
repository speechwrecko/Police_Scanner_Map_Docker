FROM python:3.6

#RUN apt-get -yqq update
#RUN apt-get -yqq install software-properties-common

#RUN add-apt-repository ppa:mc3man/trusty-media
#RUN apt-get -yqq update
#RUN apt-get -yqq dist-upgrade

#RUN apt-get -yqq update
#RUN apt-get -yqq install ffmpeg

#install AVCONV
RUN apt-get -y update
RUN apt-get install -y libav-tools libavcodec-extra

#install MP3
RUN apt-get -y update
RUN apt-get install -y libmp3lame-dev

# copy our application code
ADD . /opt/flask-app
WORKDIR /opt/flask-app

ENV GOOGLE_APPLICATION_CREDENTIALS="/opt/flask-app/My First Project-78e8d00c9ed7.json"
ENV LOGGLY_ACCOUNT=JasonFlaks
ENV LOGGLY_AUTH=93ef087d-4b3f-48f5-a1d5-0d60755fa966

# fetch app specific deps
RUN pip install -r requirements.txt

# expose port
EXPOSE 5000
EXPOSE 514
EXPOSE 514/udp

# start app
CMD [ "python", "./application.py" ]