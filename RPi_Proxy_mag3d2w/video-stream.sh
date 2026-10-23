#!/bin/bash
. ./video-stream.ini


killall gst-launch-1.0
killall ffmpeg

if [ "$engine" = "ffmpeg" ];
then
     v4l2-ctl -d /dev/video11 --set-ctrl=h264_i_frame_period=60 --set-ctrl=repeat_sequence_header=1 --set-ctrl=h264_profile=0  --set-ctrl=sequence_header_mode=0

      ffmpeg -re -s $video_width\x$video_height -f video4linux2 -i $usb_camera -r $video_frame \
          -vf "drawtext ='fontfile=/usr/share/fonts/truetype/ttf-dejavu/DejaVuSans-Bold.ttf: text =$apparatus_location ($apparatus_name $apparatus_id) - %{localtime\:%X}:fontsize=$font_size:fontcolor=black:box=1:boxcolor=white@0.5: x = 10: y = 10'" \
          -pix_fmt yuv420p -an -c:v  h264_v4l2m2m  -b:v 1024k   \
          -f rtp "rtp://$video_server:$video_port/?pkt_size=1300"

else

      gst-launch-1.0 v4l2src device=$usb_camera ! video/x-raw,width=$video_width,height=$video_height,framerate=$video_frame/1 !\
      clockoverlay time-format="%x - %X" ! videoconvert ! omxh264enc ! h264parse ! rtph264pay config-interval=1 pt=96 !\
      udpsink host=$video_server port=$video_port async=false


fi
##	  -bsf:v extract_extradata,dump_extra \
