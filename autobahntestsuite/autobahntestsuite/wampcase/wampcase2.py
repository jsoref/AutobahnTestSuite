###############################################################################
##
##  Copyright 2013 Tavendo GmbH
##
##  Licensed under the Apache License, Version 2.0 (the "License");
##  you may not use this file except in compliance with the License.
##  You may obtain a copy of the License at
##
##      http://www.apache.org/licenses/LICENSE-2.0
##
##  Unless required by applicable law or agreed to in writing, software
##  distributed under the License is distributed on an "AS IS" BASIS,
##  WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
##  See the License for the specific language governing permissions and
##  limitations under the License.
##
###############################################################################

__all__ = ["WampCase2_x_x"]


import sys, pickle, json, time
from pprint import pprint
from collections import namedtuple

from twisted.python import log
from twisted.internet import reactor

from twisted.internet.defer import Deferred, DeferredList

from autobahn.websocket import WebSocketClientProtocol, connectWS

from autobahn.wamp import WampClientFactory, \
                          WampClientProtocol, WampCraClientProtocol

from testrun import TestResult

Telegram = namedtuple("Telegram", ["time", "session_id", "direction", "payload"])


class WampCase2_x_x_Base:

   def __init__(self, testee, debugWs = False, debugWamp = False):
      self.url = testee.url
      self.auth = testee.auth
      self.debugWs = debugWs
      self.debugWamp = debugWamp

      self.result = TestResult()
      self.result.received = {}
      self.result.expected = {}
      self.result.log = []

      self.sentIndex = 0


   def done(self, _):
      self.result.ended = time.clock()
      passed = json.dumps(self.result.received) == json.dumps(self.result.expected)
      self.result.passed = passed
      self.finished.callback(self.result)


   def shutdown(self):
      for c in self.clients:
         c.proto.sendClose()


   def run(self):
      self.result.started = time.clock()

      self.clients = []
      fireOnConnected = []
      fireOnClosed = []
      i = 1
      for c in self.settings.PEERS:
         d = Deferred()
         g = Deferred()
         c = TestFactory(self, d, g, subscribeTopics = c)
         c.name = "Peer %d" % i
         self.clients.append(c)
         fireOnConnected.append(d)
         fireOnClosed.append(g)
         connectWS(c)
         i += 1

      def dotest():
         if self.sentIndex < len(self.payloads):

            publisher = self.clients[0]

            ## map exclude indices to session IDs
            ##
            exclude = []
            for i in self.settings.EXCLUDE:
               exclude.append(self.clients[i].proto.session_id)

            if self.settings.EXCLUDE_ME is None:
               if len(exclude) > 0:
                  publisher.proto.publish(self.settings.PUBLICATION_TOPIC,
                                          self.payloads[self.sentIndex],
                                          exclude = exclude)
               else:
                  publisher.proto.publish(self.settings.PUBLICATION_TOPIC,
                                          self.payloads[self.sentIndex])
            else:
               if len(exclude) > 0:
                  publisher.proto.publish(self.settings.PUBLICATION_TOPIC,
                                          self.payloads[self.sentIndex],
                                          excludeMe = self.settings.EXCLUDE_ME,
                                          exclude = exclude)
               else:
                  publisher.proto.publish(self.settings.PUBLICATION_TOPIC,
                                          self.payloads[self.sentIndex],
                                          excludeMe = self.settings.EXCLUDE_ME)
            self.sentIndex += 1
            reactor.callLater(0, dotest)
            #dotest()
         else:
            #self.shutdown()
            reactor.callLater(0.5, self.shutdown)

      def connected(res):
         ## setup what we expected, and what we actually received
         ##
         for c in self.clients:
            self.result.expected[c.proto.session_id] = []
            self.result.received[c.proto.session_id] = []

         receivers = [self.clients[i] for i in self.settings.RECEIVERS]

         for c in receivers:
            for d in self.payloads:
               self.result.expected[c.proto.session_id].append(
                  (self.settings.PUBLICATION_TOPIC, d))
         reactor.callLater(0.1, dotest)
         #dotest()

      def error(err):
         print err

      DeferredList(fireOnConnected).addCallbacks(connected, error)
      DeferredList(fireOnClosed).addCallbacks(self.done, error)

      self.finished = Deferred()
      return self.finished



class TestProtocol(WampCraClientProtocol):

   def onSessionOpen(self):
      if self.factory.auth:
         d = self.authenticate(**self.factory.auth)
         d.addCallback(self.initializeSubscriptions)
         d.addErrback(self.printError)
      else:
         self.initializeSubscriptions()

   def initializeSubscriptions(self, res=None):
      for topic in self.factory.subscribeTopics:
         self.subscribe(topic, self.onEvent)
      self.factory.onReady.callback(self.session_id)

   def sendMessage(self, payload, binary = False):
      session_id = self.session_id if hasattr(self, 'session_id') else None
      now = round(1000000 * (time.clock() - self.factory.case.result.started))
      telegram = Telegram(now, session_id, "TX", payload)
      self.factory.case.result.log.append(telegram)
      WebSocketClientProtocol.sendMessage(self, payload, binary)

   def onMessage(self, payload, binary):
      session_id = self.session_id if hasattr(self, 'session_id') else None
      now = round(1000000 * (time.clock() - self.factory.case.result.started))
      telegram = Telegram(now, session_id, "RX", payload)
      self.factory.case.result.log.append(telegram)
      WampClientProtocol.onMessage(self, payload, binary)

   def onEvent(self, topic, event):
      if not self.factory.case.result.received.has_key(self.session_id):
         self.factory.case.result.received[self.session_id] = []
      self.factory.case.result.received[self.session_id].append((topic, event))

   def printError(self, err):
      print err


class TestFactory(WampClientFactory):

   protocol_cls = TestProtocol

   def __init__(self, case, onReady, onGone, subscribeTopics):
      WampClientFactory.__init__(self, case.url, debug = case.debugWs,
                                 debugWamp = case.debugWamp)
      self.case = case
      self.auth = self.case.auth
      self.onReady = onReady
      self.onGone = onGone
      self.subscribeTopics = subscribeTopics

   def buildProtocol(self, addr):
      self.proto = self.protocol_cls()
      self.proto.factory = self
      return self.proto

   def clientConnectionLost(self, connector, reason):
      self.onGone.callback(None)


   def clientConnectionFailed(self, connector, reason):
      self.onGone.callback(None)


      
## the set of cases we construct and export from this module
##
WampCase2_x_x = []

class Settings:
   def __init__(self, peers, publicationTopic, excludeMe, exclude, eligible,
                receivers):
      self.PEERS = peers
      self.PUBLICATION_TOPIC = publicationTopic
      self.EXCLUDE_ME = excludeMe
      self.EXCLUDE = exclude
      self.ELIGIBLE = eligible
      self.RECEIVERS = receivers

   def __repr__(self):
      repr = ["Peers: %s" % self.PEERS,
              "Publication topic: %s" % self.PUBLICATION_TOPIC,
              "Clients to exclude: %s" % self.EXCLUDE,
              "Exclude me: %s" % self.EXCLUDE_ME,
              "Eligible: %s" % self.ELIGIBLE,
              "Receivers: %s" % self.RECEIVERS]

      # TODO: Move HTML code to template
      return "- " + "\n<br>- ".join(repr)

## the topic our test publisher will publish to
##
TOPIC_PUBLISHED_TO = "http://example.com/simple"

## some topic the test publisher will NOT publish to
##
TOPIC_NOT_PUBLISHED_TO = "http://example.com/foobar"


## for each peer, list of topics the peer subscribes to
## the publisher is always the first peer in this list
##
PEERSET1 = [
              [TOPIC_PUBLISHED_TO],
              [TOPIC_PUBLISHED_TO]
           ]

## these settings control the options the publisher uses
## during publishing
##
SETTINGS1 = [Settings(PEERSET1, TOPIC_PUBLISHED_TO, None, [], None, [1]),
             Settings(PEERSET1, TOPIC_PUBLISHED_TO, True, [], None, [1]),
             Settings(PEERSET1, TOPIC_PUBLISHED_TO, False, [], None, [0, 1]),
             Settings(PEERSET1, TOPIC_PUBLISHED_TO, False, [0], None, [1]),
             Settings(PEERSET1, TOPIC_PUBLISHED_TO, None, [1,], None, [0]),
             Settings(PEERSET1, TOPIC_PUBLISHED_TO, None, [0, 1], None, []),
            ]

PEERSET2 = [
              [TOPIC_PUBLISHED_TO],
              [TOPIC_PUBLISHED_TO],
              [TOPIC_PUBLISHED_TO, TOPIC_NOT_PUBLISHED_TO],
              [TOPIC_NOT_PUBLISHED_TO],
              []
           ]

SETTINGS2 = [Settings(PEERSET2, TOPIC_PUBLISHED_TO, None, [], None, [1, 2]),
             Settings(PEERSET2, TOPIC_PUBLISHED_TO, True, [], None, [1, 2]),
             Settings(PEERSET2, TOPIC_PUBLISHED_TO, False, [], None, [0, 1, 2]),
             Settings(PEERSET2, TOPIC_PUBLISHED_TO, False, [0], None, [1, 2]),
             Settings(PEERSET2, TOPIC_PUBLISHED_TO, None, [2], None, [0, 1]),
             Settings(PEERSET2, TOPIC_PUBLISHED_TO, None, [1, 2], None, [0]),
             Settings(PEERSET2, TOPIC_PUBLISHED_TO, None, [0, 1, 2], None, []),
            ]

SETTINGS = []
for settings in [SETTINGS1, SETTINGS2]:
   SETTINGS.extend(settings)

## the event payload the publisher sends in one session
##
PAYLOADS = [[None],
            [100],
            [0.1234],
            [-1000000],
            ["hello"],
            [True],
            [False],
            [666, 23, 999],
            [{}],
            [100, "hello", {u'foo': u'bar'},
             [1, 2, 3],
             ["hello", 20, {'baz': 'poo'}]]
            ]

## now dynamically create case classes
##
j = 1
for s in SETTINGS:
   i = 1
   for d in PAYLOADS:
      DESCRIPTION = "- Payload: %s\n<br>%s" % (d ,s)
      EXPECTATION = ""
      C = type("WampCase2_%d_%d" % (j, i),
               (object, WampCase2_x_x_Base, ),
               {"__init__": WampCase2_x_x_Base.__init__,
                "run": WampCase2_x_x_Base.run,
                "DESCRIPTION": """%s""" % DESCRIPTION,
                "EXPECTATION": """%s""" % EXPECTATION,
                "payloads": d,
                "settings": s})
      WampCase2_x_x.append(C)
      i += 1
   j += 1
