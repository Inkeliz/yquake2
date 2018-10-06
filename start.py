from configparser import SafeConfigParser
from simplecrypt import encrypt, decrypt
from nano25519 import ed25519_oop as ed25519
from pyblake2 import blake2b
from subprocess import Popen, PIPE
import binascii, time, io, pyqrcode, random, getpass, socket, sys
import tornado.gen, tornado.ioloop, tornado.iostream, tornado.tcpserver
from modules import nano

raw_in_xrb = 1000000000000000000000000000000.0
HOST = '127.0.0.1'  # Standard loopback interface address (localhost)
PORT = 65432        # Port to listen on (non-privileged ports are > 1023)

def display_qr(account):
    data = 'xrb:' + account
    xrb_qr = pyqrcode.create(data, encoding='iso-8859-1')
    print(xrb_qr.terminal())

def wait_for_reply(account):
    pending = nano.get_pending(str(account))
    while len(pending) == 0:
       pending = nano.get_pending(str(account))
       time.sleep(2)
       print('.', end='', flush=True)

    print()

def read_encrypted(password, filename, string=True):
    with open(filename, 'rb') as input:
        ciphertext = input.read()
        plaintext = decrypt(password, ciphertext)
        if string:
            return plaintext.decode('utf8')
        else:
            return plaintext

def write_encrypted(password, filename, plaintext):
    with open(filename, 'wb') as output:
        ciphertext = encrypt(password, plaintext)
        output.write(ciphertext)

class SimpleTcpClient(object):
    client_id = 0
    
    def __init__(self, stream, account, wallet_seed, index):
        super().__init__()
        SimpleTcpClient.client_id += 1
        self.id = SimpleTcpClient.client_id
        self.stream = stream
        self.account = account
        self.wallet_seed = wallet_seed
        self.index = index
        
        self.stream.socket.setsockopt(
            socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        self.stream.socket.setsockopt(
            socket.IPPROTO_TCP, socket.SO_KEEPALIVE, 1)
        self.stream.set_close_callback(self.on_disconnect)


    @tornado.gen.coroutine
    def on_disconnect(self):
        self.log("disconnected")
        yield []

    @tornado.gen.coroutine
    def on_connect(self):
        raddr = 'closed'
        try:
            raddr = '%s:%d' % self.stream.socket.getpeername()
        except Exception:
            pass
        self.log('new, %s' % raddr)

        yield self.dispatch_client()

    def log(self, msg, *args, **kwargs):
        print('[connection %d] %s' % (self.id, msg.format(*args, **kwargs)))

    @tornado.gen.coroutine
    def dispatch_client(self):
        try:
            while True:
                line = yield self.stream.read_until(b'\n')
                self.log('got |%s|' % line.decode('utf-8').strip())
                yield self.stream.write(line)
                print("{} {}".format(time.strftime("%d/%m/%Y %H:%M:%S"),line))
                split_data = line.rstrip().decode('utf8').split(",")
                
                if split_data[0] == "shutdown":
                    print("Shutdown Socket Server and Exit")
                    tornado.ioloop.IOLoop.instance().stop()
                    sys.exit()
                
                elif split_data[0] == "pay_server":
                    print("Pay Nano to Server")
                    dest_account = 'xrb_' + split_data[1]
                    amount = str(100000000000000000000000000000)
                    print("account: {} seed: {} index: {} amount: {}".format(self.account, self.wallet_seed, self.index, amount))
                    yield nano.send_xrb(dest_account, int(amount), self.account, int(self.index), self.wallet_seed)

        except tornado.iostream.StreamClosedError:
                pass

class SimpleTcpServer(tornado.tcpserver.TCPServer):
    
    def __init__(self, account, wallet_seed, index):
        super().__init__()
        self.account = account
        self.wallet_seed = wallet_seed
        self.index = index
    
    @tornado.gen.coroutine
    def handle_stream(self, stream, address):
        """
            Called for each new connection, stream.socket is
            a reference to socket object
            """
        connection = SimpleTcpClient(stream, self.account, self.wallet_seed, self.index)
        yield connection.on_connect()

@tornado.gen.coroutine
def check_account(account, wallet_seed, index):
    print("Check for blocks")
    pending = nano.get_pending(str(account))
    print("Pending Len:" + str(len(pending)))
    
    while len(pending) > 0:
        pending = nano.get_pending(str(account))
        print(len(pending))
        nano.receive_xrb(int(index), account, wallet_seed)

def main():
    print("Starting Nanoquake2")

    parser = SafeConfigParser()
    config_files = parser.read('config.ini')

    while True:
        password = getpass.getpass('Enter password: ')
        password_confirm = getpass.getpass('Confirm password: ')
        if password == password_confirm:
            break
        print("Password Mismatch!")

    if len(config_files) == 0:
        print("Generating Wallet Seed")
        full_wallet_seed = hex(random.SystemRandom().getrandbits(256))
        wallet_seed = full_wallet_seed[2:].upper()
        print("Wallet Seed (make a copy of this in a safe place!): ", wallet_seed)
        write_encrypted(password, 'seed.txt', wallet_seed)

        cfgfile = open("config.ini",'w')
        parser.add_section('wallet')

        priv_key, pub_key = nano.seed_account(str(wallet_seed), 0)
        public_key = str(binascii.hexlify(pub_key), 'ascii')
        print("Public Key: ", str(public_key))

        account = nano.account_xrb(str(public_key))
        print("Account Address: ", account)

        parser.set('wallet', 'account', account)
        parser.set('wallet', 'index', '0')

        parser.write(cfgfile)
        cfgfile.close()

        index = 0
        seed = wallet_seed

    else:
        print("Config file found")
        print("Decoding wallet seed with your password")
        try:
            wallet_seed = read_encrypted(password, 'seed.txt', string=True)
        except:
            print('\nError decoding seed, check password and try again')
            sys.exit()

    account = parser.get('wallet', 'account')
    index = int(parser.get('wallet', 'index'))

    print(account)
    print(index)

    display_qr(account)
    print("This is your game account address: {}".format(account))

    previous = nano.get_previous(str(account))
    pending = nano.get_pending(str(account))
    #print(previous)

    if (len(previous) == 0) and (len(pending) == 0):
        print("Please send at least 0.1Nano to this account")
        print("Waiting for funds...")
        wait_for_reply(account)
    else:
        print('You already have enough balance, great!')

    pending = nano.get_pending(str(account))
    if (len(previous) == 0) and (len(pending) > 0):
        print("Opening Account")
        nano.open_xrb(int(index), account, wallet_seed)

    print("Rx Pending: ", pending)
    pending = nano.get_pending(str(account))
    print("Pending Len:" + str(len(pending)))

    while len(pending) > 0:
        pending = nano.get_pending(str(account))
        print(len(pending))
        nano.receive_xrb(int(index), account, wallet_seed)

    print("Starting Quake2")
    game_args = "+set nano_address {} +set vid_fullscreen 0".format(account[4:])
    print(game_args) 
    full_command = "release/quake2 " + game_args
    print(full_command)

    process = Popen(["release/quake2", game_args, "&"], stdout=PIPE, encoding='utf8', shell=True)

    # tcp server
    server = SimpleTcpServer(account, wallet_seed, index)
    server.listen(PORT, HOST)
    print("Listening on %s:%d..." % (HOST, PORT))
    
    #
    pc = tornado.ioloop.PeriodicCallback(lambda: check_account(account, wallet_seed, index), 10000)
    pc.start()
    
    # infinite loop
    tornado.ioloop.IOLoop.instance().start()

print("Done")

if __name__ == "__main__":
    
    main()