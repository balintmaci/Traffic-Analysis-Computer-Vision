#!/usr/bin/env python2.7

"""
    Module with class KalmanMultiTrackerReceiver. This class utilizes MultiTrackerReceiver from package "tracking" and RTKalmanFilter from package "kalman_filter" to follow multiple tracked objects visually tracked by a MultiTracker node.

    Change log: 
    Created     frnyb       20200402
    
    Changed shebang to Python 2.7
                frnyb       20200410
"""

########################################################################
# Imports:

import sys
import threading
import argparse

import cv2
import numpy as np

import rospy

from kalman_filter.rt_kalman_filter import RTKalmanFilter
from filterpy.common import Q_discrete_white_noise

from multi_tracker_receiver import MultiTrackerReceiver

from ros_video.ros_img_stream import ROSImageStream

########################################################################
# Classes:

class KalmanMultiTrackerReceiver():
    class KalmanTrackerReceiver(RTKalmanFilter):
        def __init__(
                self,
                dt_prediction=0.05,
                prediction_topic=None,
                update_topic=None,
                state_est_topic="/rt_kalman_filter/state_est",
                start_pos=None
        ):
            self.dt_prediction = dt_prediction

            self.prediction_topic = prediction_topic
            self.update_topic = update_topic
            self.state_est_topic = state_est_topic

            self.sensor_bag = None
            self.sensor_topic = None

            self.pub_prediction = None
            self.pub_update = None
            self.pub_state_est = None

            x = None

            if start_pos != None:
                x = np.array([
                    [0.],   #px
                    [0.],   #py
                    [0.],   #vx
                    [0.]]   #vy
                )
            else:
                x = np.array([
                    [start_pos[0, 0]],
                    [start_pos[1, 0]],
                    [0.],
                    [0.]]
                )

            F = np.array([
                        [1., 0, self.dt_prediction, 0], 
                        [0., 1., 0., self.dt_prediction],
                        [0., 0., 1., 0.], 
                        [0., 0., 0., 1.]]
            )
            H = np.array([
                [0., 1., 0., 0.],
                [1., 0., 0., 0.]]
            )
            P = np.array([
                [100000. ,0., 0., 0.], 
                [0., 100000., 0., 0.],
                [0., 0., 100000., 0.],
                [0., 0., 0., 100000.]]
            )
            R = np.array([
                [1.5, 0],
                [0., 1.5]]
            )
            Q = Q_discrete_white_noise(dim=4, var=0.13)

            self.init_filter(
                    x,
                    F,
                    H,
                    P,
                    R,
                    Q
            )

            self.filter_lock = threading.Lock()

            self.update_thread = None
            self.prediction_thread = None

    def __init__(
            self,
            max_tracked_objects=30,
            dt_prediction=0.05,
            prediction_topic=None,
            update_topic=None,
            state_est_topic="/kalman_multi_tracker/state_est",
            in_events_topic="/multi_tracker/global_events",
            in_status_topic="/multi_tracker/status",
            in_window_topic="/multi_tracker/window",
            out_kalman_topic="/multi_tracker/pos",
            in_frames_topic=None,
            out_frames_topic=None
    ):
        self.max_tracked_objects = max_tracked_objects
        self.dt_prediction = dt_prediction

        self.prediction_topic = prediction_topic
        self.update_topic = update_topic
        self.state_est_topic = state_est_topic
        self.in_events_topic = in_events_topic
        self.in_status_topic = in_status_topic
        self.in_window_topic = in_window_topic
        self.out_kalman_topic = out_kalman_topic
        self.in_frames_topic = in_frames_topic
        self.out_frames_topic = out_frames_topic

        self.kalman_filters = {} # {"key":KalmanTrackerReceiver}
        self.kalman_filters_lock = threading.Lock()

        self.multi_tracker_receiver = MultiTrackerReceiver(
                max_tracked_objects=self.max_tracked_objects,
                event_callback=self.event_callback,
                status_callback=self.status_callback,
                position_callback=self.position_callback,
                in_events_topic=self.in_events_topic,
                in_status_topic=self.in_status_topic,
                in_window_topic=self.in_window_topic,
                out_kalman_topic=self.out_kalman_topic
        )

    def start(
            self,
            loop=True
    ):
        if self.in_frames_topic is not None and self.out_frames_topic is not None:
            self.pub = ROSImageStream(pub_topic_name=self.out_frames_topic)
            self.sub = ROSImageStream(sub_topic_name=self.in_frames_topic)
            self.sub.img_stream_subscribe(
                    callback=self.publish_frame,
                    loop=False
            )

        self.multi_tracker_receiver.start(loop=loop)

    def publish_frame(
            self,
            frame
    ):
        self.kalman_filters_lock.acquire()

        for k in self.kalman_filters.keys():
            frame = cv2.circle(
                    frame,
                    (int(self.kalman_filters[k].filter.x[0,0]), int(self.kalman_filters[k].filter.x[1,0])),
                    10,
                    (255,0,0)
            )

        self.pub.publish_single(frame)

        self.kalman_filters_lock.release()

    def event_callback(
            self,
            key,
            event
    ):
        self.kalman_filters_lock.acquire()
        if event == "+":
            #    self.kalman_filters[key] = None
            #self.kalman_filters[key] = self.KalmanTrackerReceiver(
            #        dt_prediction=self.dt_prediction,
            #        prediction_topic=self.prediction_topic,
            #        update_topic=self.update_topic,
            #        state_est_topic=self.state_est_topic
            #)

            #self.kalman_filters[key].start()
            #if key in self.kalman_filters.keys():
            #    self.kalman_filters[key].stop()
            #    self.kalman_filters[key] = None
            pass

        elif event == "-":
            if key in self.kalman_filters.keys():
                self.kalman_filters[key].stop()
                del self.kalman_filters[key]

        self.kalman_filters_lock.release()

    def status_callback(
            self,
            key,
            status
    ):
        self.kalman_filters_lock.acquire()

        if status == "lost":
            if key in self.kalman_filters.keys():
                callbacks = {
                        "prediction": {
                            "callback": self.multi_tracker_receiver.supply_kalman_estimate,
                            "arg": key
                        } 
                }

                self.kalman_filters[key].set_callbacks(callbacks)
        
        elif status == "ok" or status == "removed":
            if key in self.kalman_filters.keys():
                self.kalman_filters[key].set_callbacks(None)

        self.kalman_filters_lock.release()

    def position_callback(
            self,
            key,
            position
    ):
        self.kalman_filters_lock.acquire()
        
        if key not in self.kalman_filters.keys():
            self.kalman_filters[key] = self.KalmanTrackerReceiver(
                    dt_prediction=self.dt_prediction,
                    prediction_topic=self.prediction_topic,
                    update_topic=self.update_topic,
                    state_est_topic=self.state_est_topic,
                    start_pos=position
            )

            self.kalman_filters[key].start()
        else:
            self.kalman_filters[key].update_step(position)

        self.kalman_filters_lock.release()

########################################################################
# Methods:

def get_args():
    sys.argv = rospy.myargv(argv=sys.argv)

    parser = argparse.ArgumentParser()

    parser.add_argument(
            "-n",
            help="The node name.",
            type=str,
            action="store",
            default="kalman_multi_tracker"
    )

    parser.add_argument(
            "-o",
            help="The output Kalman estimated position topic.",
            type=str,
            action="store",
            default="/kalman_multi_tracker/state_est"
    )

    parser.add_argument(
            "--prediction-topic",
            help="The output prediction positions topic.",
            type=str,
            action="store",
            default=None
    )

    parser.add_argument(
            "--update-topic",
            help="The output update positions topic.",
            type=str,
            action="store",
            default=None
    )

    parser.add_argument(
            "--events-topic",
            help="Topic to communicate global events over.",
            type=str,
            action="store",
            default="/multi_tracker/global_events"
    )

    parser.add_argument(
            "--status-topic",
            help="The topic to communicate tracked objects status over.",
            type=str,
            action="store",
            default="/multi_tracker/status"
    )

    parser.add_argument(
            "--window-topic",
            help="The topic to communicate tracking windows over.",
            type=str,
            action="store",
            default="/multi_tracker/window"
    )

    parser.add_argument(
            "--kalman-topic",
            help="The topic on which to feed back Kalman filter positions when objects are lost.",
            type=str,
            action="store",
            default="/multi_tracker/pos"
    )

    return parser.parse_args(sys.argv[1:])

########################################################################
# Main:

if __name__ == '__main__':
    args = get_args()

    rospy.init_node(
            args.n,
            disable_signals=True
    )

    kmtr = KalmanMultiTrackerReceiver( 
            prediction_topic=args.prediction_topic,
            update_topic=args.update_topic,
            state_est_topic=args.o,
            in_events_topic=args.events_topic,
            in_status_topic=args.status_topic,
            in_window_topic=args.window_topic,
            out_kalman_topic=args.kalman_topic
    )

    kmtr.start()

