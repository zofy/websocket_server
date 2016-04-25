import json
import logging
import signal

import datetime
from random import randint

import tornado.httpserver
import tornado.websocket
import tornado.ioloop
import tornado.web
import socket
import os
import django

# from kernel import Game
from tornado.options import options

'''
This is a simple Websocket Echo server that uses the Tornado websocket handler.
Please run `pip install tornado` with python of version 2.7.9 or greater to install tornado.
This program will echo back the reverse of whatever it recieves.
Messages are output to the terminal for debuggin purposes.
'''

is_closing = False


def signal_handler(signum, frame):
    global is_closing
    logging.info('exiting...')
    is_closing = True


def try_exit():
    global is_closing
    if is_closing:
        # clean up here
        tornado.ioloop.IOLoop.instance().stop()
        logging.info('exit success')


class WSHandler(tornado.websocket.WebSocketHandler):
    clients = []
    users = {}
    connections = {}
    games = {}
    players = {}
    established = {}

    def open(self):
        print 'new connection'
        WSHandler.clients.append(self)

    def on_message(self, message):
        print 'message received:  %s' % message
        self.check_message(message)
        # Reverse Message and send it back
        # print 'sending back message: %s' % message[::-1]
        # self.write_message(message[::-1])

    def on_close(self):
        print 'connection closed'
        self.user_logout()
        WSHandler.clients.remove(self)

    def check_origin(self, origin):
        host = self.request.headers.get('Host')
        print(host)
        print(origin)
        return True

    # checks whether message contains json
    def check_message(self, message):
        try:
            msg = json.loads(message)
        except:
            print('No json file')
            self.send_chat_message(message)
        else:
            if 'status' in msg:
                self.read_json(msg)

    def read_json(self, msg):
        if msg['status'] == 0:
            self.manage_0(msg)
        elif msg['status'] == 1:
            self.manage_1(msg)
        elif msg['status'] == 2:
            self.manage_2(msg)

    def send_chat_message(self, msg):
        try:  # in case somehow comes bad message
            # msg = msg.strip('\n') already covered in js
            print(msg)
            WSHandler.connections[self].write_message(json.dumps({'message': msg}))
        except KeyError:
            print('Connection does not exist!')

    def end_game(self, msg):
        opponent = WSHandler.connections[self]
        opponent.write_message(json.dumps({"end": msg['end']}))

    def manage_0(self, msg):
        if 'request' in msg:
            self.send_request(msg['request'])
        elif 'answer' in msg:
            self.send_answer(msg['answer'])
        else:
            self.manage_user(msg['name'])

    def manage_1(self, msg):
        # WSHandler.games.setdefault(self, Game())
        if 'refresh' in msg:
            WSHandler.games[self].refresh()
        else:
            self.player_vs_computer(msg['point'])

    def manage_2(self, msg):
        if 'point' in msg:
            self.player_vs_player(msg['point'])
        elif 'color' in msg:
            opponent = WSHandler.connections[self]
            opponent.write_message(json.dumps({"color": msg['color']}))
        elif 'end' in msg:
            self.end_game(msg)
        elif 'refresh' in msg:
            opponent = WSHandler.connections[self]
            opponent.write_message(json.dumps({"refresh": 1}))
        elif 'connection' in msg:
            print('Connecting players...')
            p1 = msg['connection'][0]
            p2 = msg['connection'][1]
            pc = tornado.ioloop.PeriodicCallback(lambda: self.check_connection(p1, p2), 100)
            WSHandler.established[self] = pc
            pc.start()
            tornado.ioloop.IOLoop.instance().add_timeout(datetime.timedelta(seconds=3),
                                                         lambda: self.stop_checking(p1, p2))
        else:
            print('Adding player ' + msg['name'])
            WSHandler.players[msg['name']] = self
            WSHandler.players[self] = msg['name']

    def send_colors(self):
        num1 = [str(randint(0, 255)) for x in xrange(0, 3)]
        num2 = [str(randint(0, 255)) for x in xrange(0, 3)]
        color1 = 'rgb(' + ', '.join(num1) + ')'
        color2 = 'rgb(' + ', '.join(num2) + ')'
        self.write_message(json.dumps({'me': color1, 'opponent': color2}))
        WSHandler.connections[self].write_message(json.dumps({'me': color2, 'opponent': color1}))

    # waiting for players to connect
    def check_connection(self, p1, p2):
        if p1 in WSHandler.players and p2 in WSHandler.players:
            WSHandler.established[self].stop()
            WSHandler.connections[WSHandler.players[p1]] = WSHandler.players[p2]
            WSHandler.connections[WSHandler.players[p2]] = WSHandler.players[p1]
            self.send_colors()
            self.write_message(json.dumps({"go": 1}))

    def stop_checking(self, p1, p2):
        if not (p1 in WSHandler.players and p2 in WSHandler.players):
            WSHandler.established[self].stop()
            self.write_message(json.dumps({"connection_drop": 'Opponent'}))
            del WSHandler.established[self]

    def player_vs_player(self, point_idx):
        try:
            opponent = WSHandler.connections[self]
        except KeyError:
            print('Connection probably dropped down.')
        else:
            print('sending point')
            opponent.write_message(json.dumps({"point": point_idx}))
            opponent.write_message(json.dumps({"go": 1}))

    def player_vs_computer(self, p_point):
        point = WSHandler.games[self].create_point(p_point)
        c_point = WSHandler.games[self].play(point)  # kernel computes his move
        if c_point[0] is None:
            self.write_message(
                json.dumps({"end": c_point[1],
                            "point": c_point[2]}))  # server sends msg (his move) to user
        else:
            self.write_message(json.dumps({"point": c_point}))
        print(c_point)

    def send_msg_to_users(self):
        for user in WSHandler.users:
            user.write_message('make_request')

    def find_user(self, name):
        for user in WSHandler.users:
            if WSHandler.users[user] == name:
                return user

    def send_request(self, name):
        requested_user = self.find_user(name)
        if requested_user is None:
            self.write_message(json.dumps({"connection_drop": name}))
            return
        if requested_user in WSHandler.connections:
            self.write_message(json.dumps({"answer": 'unavailable', "player": name}))
        else:
            WSHandler.connections[self] = requested_user
            WSHandler.connections[requested_user] = self
            requested_user.write_message(json.dumps({"name": WSHandler.users[self]}))
        print(self.connections)

    def send_answer(self, answer):
        challenger = WSHandler.connections[self]
        challenger.write_message(json.dumps({"answer": answer, "player": WSHandler.users[self]}))
        if answer == 'Refuse':
            self.delete_connections()

    def delete_connections(self):
        try:
            del WSHandler.connections[WSHandler.connections[self]]
            del WSHandler.connections[self]
        except KeyError:
            pass

    def manage_user(self, name):
        if name not in WSHandler.users:
            # MenuUser.objects.create_menu_user(name=name)  # create logged user
            WSHandler.users[self] = name
            self.send_msg_to_users()
            print(WSHandler.users)

    def user_logout(self):
        if self in WSHandler.users:
            self.logout0()
        elif self in WSHandler.games:
            del WSHandler.games[self]
            print('Games: ', WSHandler.games)
        elif self in WSHandler.connections or self in WSHandler.players:
            self.logout2()

    def logout0(self):
        try:
            pass
            # MenuUser.objects.delete_menu_user(name=WSHandler.users[self])  # delete logged user from db
        except:
            pass
        self.delete_connections()
        del WSHandler.users[self]
        self.send_msg_to_users()
        print(WSHandler.users)
        # print(MenuUser.objects.all())

    def logout2(self):
        try:
            opponent = WSHandler.connections[self]
            opponent.write_message(json.dumps({"connection_drop": 'Opponent'}))
        except:
            print('Already disconnected!')
        self.delete_connections()
        name = WSHandler.players[self]
        del WSHandler.players[name]
        del WSHandler.players[self]
        print(WSHandler.players)
        print(WSHandler.connections)


application = tornado.web.Application([
    (r'/ws', WSHandler),
])

if __name__ == "__main__":
    http_server = tornado.httpserver.HTTPServer(application)
    tornado.options.parse_command_line()
    signal.signal(signal.SIGINT, signal_handler)
    http_server.listen(os.environ.get("PORT", 5000))
    myIP = socket.gethostbyname(socket.gethostname())
    print '*** Websocket Server Started at %s***' % myIP
    tornado.ioloop.PeriodicCallback(try_exit, 100).start()
    tornado.ioloop.IOLoop.instance().start()
