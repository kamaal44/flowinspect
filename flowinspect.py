#!/usr/bin/env python

__author__  = 'Ankur Tyagi (7h3rAm)'
__email__   = '7h3rAm [at] gmail [dot] com'
__version__ = '0.2'
__license__ = 'CC-BY-SA 3.0'
__status__  = 'Development'


import os, sys, shutil, argparse, operator

# adding custom modules path to system search paths list 
# for Python to be able to import flowinspect's core modules
# inspired ffrom Chopshop: https://github.com/MITRECND/chopshop/blob/master/chopshop
# and this SO answer: http://stackoverflow.com/questions/4383571/importing-files-from-different-folder-in-python
FLOWINSPECTROOTDIR = os.path.realpath(os.path.dirname(sys.argv[0]))
sys.path.insert(0, '%s/%s' % (FLOWINSPECTROOTDIR, 'core'))

from globals import configopts, opentcpflows, openudpflows
from tcphandler import handletcp
from udphandler import handleudp
from iphandler import handleip
from utils import NullDevice, printdict

try:
    import nids
except ImportError, ex:
    print '[-] Import failed: %s' % ex
    print '[-] Cannot proceed. Exiting.'
    print
    sys.exit(1)

try:
    #import re2 as re
    import re
    configopts['regexengine'] = 're'
except ImportError, ex:
    import re
    configopts['regexengine'] = 're'

try:
    from pydfa.pydfa import Rexp
    from pydfa.graph import FA
    configopts['dfaengine'] = 'pydfa'
except ImportError, ex:
    print '[!] Import failed: %s' % (ex)
    configopts['dfaengine'] = None

try:
    import pylibemu as emu
    configopts['shellcodeengine'] = 'pylibemu'
except ImportError, ex:
    print '[!] Import failed: %s' % (ex)
    configopts['shellcodeengine'] = None

try:
    import yara
    configopts['yaraengine'] = 'pyyara'
except ImportError, ex:
    print '[!] Import failed: %s' % (ex)
    configopts['yaraengine'] = None

try:
    from fuzzywuzzy import fuzz
    configopts['fuzzengine'] = 'fuzzywuzzy'
except ImportError, ex:
    print '[!] Import failed: %s' % (ex)
    configopts['fuzzengine'] = None

sys.dont_write_bytecode = True


def validatedfaexpr(expr):
    global configopts

    if re.search(r'^m[0-9][0-9]\s*=\s*', expr):
        (memberid, dfa) =  expr.split('=', 1)
        configopts['dfalist'].append(expr)
        return (memberid.strip(), dfa.strip())
    else:
        memberct = len(configopts['dfalist'])
        memberid = 'm%02d' % (memberct+1)
        configopts['dfalist'].append(expr)
        return (memberid, expr.strip())

def writetofile(filename, data):
    global configopts, opentcpflows

    try:
        if not os.path.isdir(configopts['logdir']): os.makedirs(configopts['logdir'])
    except OSError, oserr: print '[-] %s' % oserr

    try:
        if configopts['linemode']: file = open(filename, 'ab+')
        else: file = open(filename, 'wb+')
        file.write(data)
    except IOError, io: print '[-] %s' % io


def exitwithstats():
    global configopts, openudpflows, opentcpflows

    if configopts['verbose'] and (len(opentcpflows) > 0 or len(openudpflows) > 0):
        dumpopenstreams()

    print
    if configopts['packetct'] >= 0:
        print '[U] Processed: %d | Matches: %d | Shortest: %dB (#%d) | Longest: %dB (#%d)' % (
                configopts['inspudppacketct'],
                configopts['udpmatches'],
                configopts['shortestmatch']['packet'],
                configopts['shortestmatch']['packetid'],
                configopts['longestmatch']['packet'],
                configopts['longestmatch']['packetid'])

    if configopts['streamct'] >= 0:
        print '[T] Processed: %d | Matches: %d | Shortest: %dB (#%d) | Longest: %dB (#%d)' % (
                configopts['insptcpstreamct'],
                configopts['tcpmatches'],
                configopts['shortestmatch']['stream'],
                configopts['shortestmatch']['streamid'],
                configopts['longestmatch']['stream'],
                configopts['longestmatch']['streamid'])

    print '[+] Flowsrch session complete. Exiting.'

    if configopts['udpmatches'] > 0 or configopts['tcpmatches'] > 0: sys.exit(0)
    else: sys.exit(1)


def dumpopenstreams():
    global openudpflows, opentcpflows

    if len(openudpflows) > 0:
        print
        print '[DEBUG] Dumping open/tracked UDP streams: %d' % (len(openudpflows))

        for (key, value) in openudpflows.items():
            id = value['id']
            keydst = value['keydst']
            matches = value['matches']
            ctsdatasize = value['ctsdatasize']
            stcdatasize = value['stcdatasize']
            totdatasize = value['totdatasize']
            print '[DEBUG] [%08d] %s - %s (CTS: %dB | STC: %dB | TOT: %dB) [matches: %d]' % (
                    id,
                    key,
                    keydst,
                    ctsdatasize,
                    stcdatasize,
                    totdatasize,
                    matches)

    if len(opentcpflows) > 0:
        print
        print '[DEBUG] Dumping open/tracked TCP streams: %d' % (len(opentcpflows))

        for (key, value) in opentcpflows.items():
            id = value['id']
            ((src, sport), (dst, dport)) = key

            ctsdatasize = 0
            for size in value['ctspacketlendict'].values():
                ctsdatasize += size

            stcdatasize = 0
            for size in value['stcpacketlendict'].values():
                stcdatasize += size

            totdatasize = ctsdatasize + stcdatasize
            print '[DEBUG] [%08d] %s:%s %s %s:%s (CTS: %dB | STC: %dB | TOT: %dB)' % (
                    id,
                    src,
                    sport,
                    dst,
                    dport,
                    ctsdatasize,
                    stcdatasize,
                    totdatasize)

    print


def dumpargsstats(configopts):
    print '%-30s' % '[DEBUG] Input pcap:', ; print '[ \'%s\' ]' % (configopts['pcap'])
    print '%-30s' % '[DEBUG] Listening device:', ;print '[ \'%s\' ]' % (configopts['device']),
    if configopts['killtcp']:
        print '[ w/ \'killtcp\' ]'
    else:
        print

    print '%-30s' % '[DEBUG] Inspection Modes:', ;print '[',
    for mode in configopts['inspectionmodes']:
        if mode == 'regex': print '\'regex (%s)\'' % (configopts['regexengine']),
        if mode == 'fuzzy': print '\'fuzzy (%s)\'' % (configopts['fuzzengine']),
        if mode == 'dfa': print '\'dfa (%s)\'' % (configopts['dfaengine']),
        if mode == 'shellcode': print '\'shellcode (%s)\' | memory: %dK' % (configopts['shellcodeengine'], configopts['emuprofileoutsize']),
    print ']'

    if 'regex' in configopts['inspectionmodes']:
        print '%-30s' % '[DEBUG] CTS regex:', ; print '[ %d |' % (len(configopts['ctsregexes'])),
        for c in configopts['ctsregexes']:
            print '\'%s\'' % configopts['ctsregexes'][c]['regexpattern'],
        print ']'

        print '%-30s' % '[DEBUG] STC regex:', ; print '[ %d |' % (len(configopts['stcregexes'])),
        for s in configopts['stcregexes']:
            print '\'%s\'' % configopts['stcregexes'][s]['regexpattern'],
        print ']'

        print '%-30s' % '[DEBUG] RE stats:', ; print '[ Flags: %d - (' % (configopts['reflags']),
        if configopts['igncase']: print 'ignorecase',
        if configopts['multiline']: print 'multiline',
        print ') ]'

    if 'fuzzy' in configopts['inspectionmodes']:
        print '%-30s' % '[DEBUG] CTS fuzz patterns:', ; print '[ %d |' % (len(configopts['ctsfuzzpatterns'])),
        for c in configopts['ctsfuzzpatterns']:
            print '\'%s\'' % (c),
        print ']'

        print '%-30s' % '[DEBUG] STC fuzz patterns:', ; print '[ %d |' % (len(configopts['stcfuzzpatterns'])),
        for s in configopts['stcfuzzpatterns']:
            print '\'%s\'' % (s),
        print ']'

    if 'dfa' in configopts['inspectionmodes']:
        print '%-30s' % '[DEBUG] CTS dfa:', ; print '[ %d |' % (len(configopts['ctsdfas'])),
        for c in configopts['ctsdfas']:
            print '\'%s: %s\'' % (configopts['ctsdfas'][c]['memberid'], configopts['ctsdfas'][c]['dfapattern']),
        print ']'

        print '%-30s' % '[DEBUG] STC dfa:', ; print '[ %d |' % (len(configopts['stcdfas'])),
        for s in configopts['stcdfas']:
            print '\'%s: %s\'' % (configopts['stcdfas'][s]['memberid'], configopts['stcdfas'][s]['dfapattern']),
        print ']'

        print '%-30s' % '[DEBUG] DFA expression:',
        print '[ \'%s\' ]' % (configopts['dfaexpression'])

    if 'yara' in configopts['inspectionmodes']:
        print '%-30s' % '[DEBUG] CTS yara rules:', ; print '[ %d |' % (len(configopts['ctsyararules'])),
        for c in configopts['ctsyararules']:
            print '\'%s\'' % (c),
        print ']'

        print '%-30s' % '[DEBUG] STC yara rules:', ; print '[ %d |' % (len(configopts['stcyararules'])),
        for s in configopts['stcyararules']:
            print '\'%s\'' % (s),
        print ']'

    print '%-30s' % '[DEBUG] Inspection limits:',
    print '[ Streams: %d | Packets: %d | Offset: %d | Depth: %d ]' % (
            configopts['maxinspstreams'],
            configopts['maxinsppackets'],
            configopts['offset'],
            configopts['depth'])

    print '%-30s' % '[DEBUG] Display limits:',
    print '[ Streams: %d | Packets: %d | Bytes: %d ]' % (
            configopts['maxdispstreams'],
            configopts['maxdisppackets'],
            configopts['maxdispbytes'])

    print '%-30s' % '[DEBUG] Output modes:', ; print '[',
    if 'quite' in configopts['outmodes']:
        print '\'quite\'',
        if configopts['writelogs']:
            print '\'write: %s\'' % (configopts['logdir']),
    else:
        if 'meta' in configopts['outmodes']: print '\'meta\'',
        if 'hex' in configopts['outmodes']: print '\'hex\'',
        if 'print' in configopts['outmodes']: print '\'print\'',
        if 'raw' in configopts['outmodes']: print '\'raw\'',
        if 'graph' in configopts['outmodes']: print '\'graph: %s\'' % (configopts['graphdir']),
        if configopts['writelogs']: print '\'write: %s\'' % (configopts['logdir']),
    print ']'

    print '%-30s' % '[DEBUG] Misc options:',
    print '[ BPF: \'%s\' | invertmatch: %s | killtcp: %s | graph: %s | verbose: %s | linemode: %s ]' % (
            configopts['bpf'],
            configopts['invertmatch'],
            configopts['killtcp'],
            configopts['graph'],
            configopts['verbose'],
            configopts['linemode'])
    print


def main():
    banner = '''\
        ______              _                            __
       / __/ /___ _      __(_)___  _________  ___  _____/ /_
      / /_/ / __ \ | /| / / / __ \/ ___/ __ \/ _ \/ ___/ __/
     / __/ / /_/ / |/ |/ / / / / (__  ) /_/ /  __/ /__/ /_
    /_/ /_/\____/|__/|__/_/_/ /_/____/ .___/\___/\___/\__/
                                    /_/
    '''
    print '%s' % (banner)
    print '%s v%s - %s' % (configopts['name'], configopts['version'], configopts['desc'])
    print '%s' % configopts['author']
    print

    parser = argparse.ArgumentParser()

    inputgroup = parser.add_mutually_exclusive_group(required=True)
    inputgroup.add_argument(
                                    '-p',
                                    metavar='--pcap',
                                    dest='pcap',
                                    default='',
                                    action='store',
                                    help='input pcap file')
    inputgroup.add_argument(
                                    '-d',
                                    metavar='--device',
                                    dest='device',
                                    default='lo',
                                    action='store',
                                    help='listening device')

    regex_direction_flags = parser.add_argument_group('RegEx per Direction')
    regex_direction_flags.add_argument(
                                    '-c',
                                    metavar='--cregex',
                                    dest='cres',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='regex to match against CTS data')
    regex_direction_flags.add_argument(
                                    '-s',
                                    metavar='--sregex',
                                    dest='sres',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='regex to match against STC data')
    regex_direction_flags.add_argument(
                                    '-a',
                                    metavar='--aregex',
                                    dest='ares',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='regex to match against ANY data')

    regex_options = parser.add_argument_group('RegEx Options')
    regex_options.add_argument(
                                    '-i',
                                    dest='igncase',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='ignore case')
    regex_options.add_argument(
                                    '-m',
                                    dest='multiline',
                                    default=True,
                                    action='store_false',
                                    required=False,
                                    help='disable multiline match')

    fuzzy_direction_flags = parser.add_argument_group('Fuzzy Patterns per Direction')
    fuzzy_direction_flags.add_argument(
                                    '-G',
                                    metavar='--cfuzz',
                                    dest='cfuzz',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='string to fuzzy match against CTS data')
    fuzzy_direction_flags.add_argument(
                                    '-H',
                                    metavar='--sfuzz',
                                    dest='sfuzz',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='string to fuzzy match against STC data')
    fuzzy_direction_flags.add_argument(
                                    '-I',
                                    metavar='--afuzz',
                                    dest='afuzz',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='string to fuzzy match against ANY data')
    fuzzy_options = parser.add_argument_group('Fuzzy Options')
    fuzzy_options.add_argument(
                                    '-r',
                                    metavar='fuzzminthreshold',
                                    dest='fuzzminthreshold',
                                    type=int,
                                    default=75,
                                    action='store',
                                    required=False,
                                    help='threshold for fuzzy match (1-100) - default 75')

    dfa_direction_flags = parser.add_argument_group('DFAs per Direction (\'m[0-9][1-9]=<dfa>\')')
    dfa_direction_flags.add_argument(
                                    '-C',
                                    metavar='--cdfa',
                                    dest='cdfas',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='DFA expression to match against CTS data')
    dfa_direction_flags.add_argument(
                                    '-S',
                                    metavar='--sdfa',
                                    dest='sdfas',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='DFA expression to match against STC data')
    dfa_direction_flags.add_argument(
                                    '-A',
                                    metavar='--adfa',
                                    dest='adfas',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='DFA expression to match against ANY data')

    dfa_options = parser.add_argument_group('DFA Options')
    dfa_options.add_argument(
                                    '-l',
                                    dest='boolop',
                                    default=configopts['useoroperator'],
                                    action='store_true',
                                    required=False,
                                    help='switch default boolean operator to \'or\'')
    dfa_options.add_argument(
                                    '-X',
                                    metavar='--dfaexpr',
                                    dest='dfaexpr',
                                    default=None,
                                    action='store',
                                    required=False,
                                    help='expression to test chain members')

    dfa_options.add_argument(
                                    '-g',
                                    metavar='graphdir',
                                    dest='graph',
                                    default='',
                                    action='store',
                                    required=False,
                                    nargs='?',
                                    help='generate DFA transitions graph')

    yara_direction_flags = parser.add_argument_group('Yara Rules per Direction')
    yara_direction_flags.add_argument(
                                    '-P',
                                    metavar='--cyararules',
                                    dest='cyararules',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='Yara rules to match on CTS data')
    yara_direction_flags.add_argument(
                                    '-Q',
                                    metavar='--syararules',
                                    dest='syararules',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='Yara rules to match on STC data')
    yara_direction_flags.add_argument(
                                    '-R',
                                    metavar='--ayararules',
                                    dest='ayararules',
                                    default=[],
                                    action='append',
                                    required=False,
                                    help='Yara rules to match on ANY data')

    shellcode_options = parser.add_argument_group('Shellcode Detection')
    shellcode_options.add_argument(
                                    '-M',
                                    dest='shellcode',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='enable shellcode detection')
    shellcode_options.add_argument(
                                    '-y',
                                    dest='emuprofile',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='generate emulator profile for detected shellcode')
    shellcode_options.add_argument(
                                    '-Y',
                                    metavar='--emuprofileoutsize',
                                    dest='emuprofileoutsize',
                                    default=0,
                                    action='store',
                                    required=False,
                                    help='emulator profile memory size (default 1024K | max: 10240K)')

    content_modifiers = parser.add_argument_group('Content Modifiers')
    content_modifiers.add_argument(
                                    '-O',
                                    metavar='--offset',
                                    dest='offset',
                                    default=0,
                                    action='store',
                                    required=False,
                                    help='bytes to skip before matching')
    content_modifiers.add_argument(
                                    '-D',
                                    metavar='--depth',
                                    dest='depth',
                                    default=0,
                                    action='store',
                                    required=False,
                                    help='bytes to look at while matching (starting from offset)')

    inspection_limits = parser.add_argument_group('Inspection Limits')
    inspection_limits.add_argument(
                                    '-T',
                                    metavar='--maxinspstreams',
                                    dest='maxinspstreams',
                                    default=0,
                                    action='store',
                                    type=int,
                                    required=False,
                                    help='max streams to inspect')
    inspection_limits.add_argument(
                                    '-U',
                                    metavar='--maxinsppackets',
                                    dest='maxinsppackets',
                                    default=0,
                                    action='store',
                                    type=int,
                                    required=False,
                                    help='max packets to inspect')

    display_limits = parser.add_argument_group('Display Limits')
    display_limits.add_argument(
                                    '-t',
                                    metavar='--maxdispstreams',
                                    dest='maxdispstreams',
                                    default=0,
                                    action='store',
                                    type=int,
                                    required=False,
                                    help='max streams to display')
    display_limits.add_argument(
                                    '-u',
                                    metavar='--maxdisppackets',
                                    dest='maxdisppackets',
                                    default=0,
                                    action='store',
                                    type=int,
                                    required=False,
                                    help='max packets to display')
    display_limits.add_argument(
                                    '-b',
                                    metavar='--maxdispbytes',
                                    dest='maxdispbytes',
                                    default=0,
                                    action='store',
                                    type=int,
                                    required=False,
                                    help='max bytes to display')

    output_options = parser.add_argument_group('Output Options')
    output_options.add_argument(
                                    '-w',
                                    metavar='logdir',
                                    dest='writebytes',
                                    default='',
                                    action='store',
                                    required=False,
                                    nargs='?',
                                    help='write matching packets/streams')
    output_options.add_argument(
                                    '-o',
                                    dest='outmodes',
                                    choices=('quite', 'meta', 'hex', 'print', 'raw'),
                                    action='append',
                                    default=[],
                                    required=False,
                                    help='match output modes')

    misc_options = parser.add_argument_group('Misc. Options')
    misc_options.add_argument(
                                    '-f',
                                    metavar='--bpf',
                                    dest='bpf',
                                    default='',
                                    action='store',
                                    required=False,
                                    help='BPF expression')
    misc_options.add_argument(
                                    '-v',
                                    dest='invmatch',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='invert match')
    misc_options.add_argument(
                                    '-V',
                                    dest='verbose',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='verbose output')
    misc_options.add_argument(
                                    '-e',
                                    dest='colored',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='enable colored output')
    misc_options.add_argument(
                                    '-k',
                                    dest='killtcp',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='kill matching TCP stream')
    misc_options.add_argument(
                                    '-n',
                                    dest='confirm',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='confirm before initializing NIDS')
    misc_options.add_argument(
                                    '-L',
                                    dest='linemode',
                                    default=False,
                                    action='store_true',
                                    required=False,
                                    help='enable linemode (disables inspection)')

    args = parser.parse_args()

    #sys.stdout = NullDevice()

    if args.pcap:
        configopts['pcap'] = args.pcap
        nids.param('filename', configopts['pcap'])
        configopts['livemode'] = False
    elif args.device:
        configopts['device'] = args.device
        nids.param('device', configopts['device'])
        configopts['livemode'] = True

    if args.igncase:
        configopts['igncase'] = True
        configopts['reflags'] |= re.IGNORECASE

    if args.invmatch:
        configopts['invertmatch'] = True

    if args.multiline:
        configopts['multiline'] = True
        configopts['reflags'] |= re.MULTILINE
        configopts['reflags'] |= re.DOTALL

    if args.boolop:
        configopts['useoroperator'] = True

    if configopts['regexengine']:
        if args.cres:
            if 'regex' not in configopts['inspectionmodes']:
                configopts['inspectionmodes'].append('regex')
            for c in args.cres:
                configopts['ctsregexes'][re.compile(c, configopts['reflags'])] = { 'regexpattern': c }

        if args.sres:
            if 'regex' not in configopts['inspectionmodes']:
                configopts['inspectionmodes'].append('regex')
            for s in args.sres:
                configopts['stcregexes'][re.compile(s, configopts['reflags'])] = { 'regexpattern': s }

        if args.ares:
            if 'regex' not in configopts['inspectionmodes']:
                configopts['inspectionmodes'].append('regex')
            for a in args.ares:
                configopts['ctsregexes'][re.compile(a, configopts['reflags'])] = { 'regexpattern': a }
                configopts['stcregexes'][re.compile(a, configopts['reflags'])] = { 'regexpattern': a }

    if configopts['fuzzengine']:
        if args.cfuzz:
            if 'fuzzy' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('fuzzy')
            for c in args.cfuzz:
                configopts['ctsfuzzpatterns'].append(c)

        if args.sfuzz:
            if 'fuzzy' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('fuzzy')
            for s in args.sfuzz:
                configopts['stcfuzzpatterns'].append(s)

        if args.afuzz:
            if 'fuzzy' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('fuzzy')
            for a in args.afuzz:
                configopts['ctsfuzzpatterns'].append(a)
                configopts['stcfuzzpatterns'].append(a)

    if configopts['dfaengine']:
        if args.cdfas:
            if 'dfa' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('dfa')
            for c in args.cdfas:
                (memberid, dfa) = validatedfaexpr(c)

                dfaobj = Rexp(dfa)
                configopts['ctsdfas'][dfaobj] = {
                    'dfapattern': dfa,
                    'memberid': memberid,
                    'truthvalue': 'False'
                }

        if args.sdfas:
            if 'dfa' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('dfa')
            for s in args.sdfas:
                (memberid, dfa) = validatedfaexpr(s)

                dfaobj = Rexp(dfa)
                configopts['stcdfas'][dfaobj] = {
                    'dfapattern': dfa,
                    'memberid': memberid,
                    'truthvalue': 'False'
                }

        if args.adfas:
            if 'dfa' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('dfa')
            for a in args.adfas:
                (memberid, dfa) = validatedfaexpr(a)

                dfaobj = Rexp(dfa)
                configopts['ctsdfas'][dfaobj] = {
                    'dfapattern': dfa,
                    'memberid': memberid,
                    'truthvalue': 'False'
                }
                configopts['stcdfas'][dfaobj] = {
                    'dfapattern': dfa,
                    'memberid': memberid,
                    'truthvalue': 'False'
                }

        if len(configopts['ctsdfas']) > 0 or len(configopts['stcdfas']) > 0:
            if args.dfaexpr:
                configopts['dfaexpression'] = args.dfaexpr.strip().lower()
                for token in configopts['dfaexpression'].split(' '):
                    if token != 'and' and token != 'oand' and token != 'or':
                        configopts['dfaexprmembers'].append(token)
                configopts['dfaexpression'] = re.sub('oand', 'and', configopts['dfaexpression'])
            else:
                memberids = []
                for dfa in configopts['ctsdfas'].keys():
                    if configopts['ctsdfas'][dfa]['memberid'] not in memberids:
                        memberids.append(configopts['ctsdfas'][dfa]['memberid'])
                        if configopts['useoroperator']: memberids.append('or')
                        else: memberids.append('and')
                        configopts['dfaexprmembers'].append(configopts['ctsdfas'][dfa]['memberid'])

                for dfa in configopts['stcdfas'].keys():
                    if configopts['stcdfas'][dfa]['memberid'] not in memberids:
                        memberids.append(configopts['stcdfas'][dfa]['memberid'])
                        if configopts['useoroperator']: memberids.append('or')
                        else: memberids.append('and')
                        configopts['dfaexprmembers'].append(configopts['stcdfas'][dfa]['memberid'])

                del memberids[-1]
                configopts['dfaexpression'] = ' '.join(memberids)

    if configopts['yaraengine']:
        if args.cyararules:
            if 'yara' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('yara')
            for c in args.cyararules:
                if os.path.isfile(c): configopts['ctsyararules'][yara.compile(c)] = { 'filepath': c }

        if args.syararules:
            if 'yara' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('yara')
            for s in args.syararules:
                if os.path.isfile(s): configopts['stcyararules'][yara.compile(s)] = { 'filepath': s }

        if args.ayararules:
            if 'yara' not in configopts['inspectionmodes']: configopts['inspectionmodes'].append('yara')
            for a in args.ayararules:
                if os.path.isfile(a):
                    configopts['ctsyararules'][yara.compile(a)] = { 'filepath': a }
                    configopts['stcyararules'][yara.compile(a)] = { 'filepath': a }

    if args.fuzzminthreshold >= 1 and args.fuzzminthreshold <= 100:
        configopts['fuzzminthreshold'] = args.fuzzminthreshold

    if args.offset:
        configopts['offset'] = int(args.offset)

    if args.depth:
        configopts['depth'] = int(args.depth)

    if args.maxinsppackets:
        configopts['maxinsppackets'] = int(args.maxinsppackets)

    if args.maxinspstreams:
        configopts['maxinspstreams'] = int(args.maxinspstreams)

    if args.maxdisppackets:
        configopts['maxdisppackets'] = int(args.maxdisppackets)

    if args.maxdispstreams:
        configopts['maxdispstreams'] = int(args.maxdispstreams)

    if args.maxdispbytes:
        configopts['maxdispbytes'] = int(args.maxdispbytes)

    if args.writebytes != '':
        configopts['writelogs'] = True
        if args.writebytes != None:
            configopts['logdir'] = args.writebytes
        else:
            configopts['logdir'] = '.'

    if not args.outmodes:
        configopts['outmodes'].append('meta')
        configopts['outmodes'].append('hex')
    else:
        if 'quite' in args.outmodes: configopts['outmodes'].append('quite')
        if 'meta' in args.outmodes: configopts['outmodes'].append('meta')
        if 'hex' in args.outmodes: configopts['outmodes'].append('hex')
        if 'print' in args.outmodes: configopts['outmodes'].append('print')
        if 'raw' in args.outmodes: configopts['outmodes'].append('raw')

    if args.graph != '':
        configopts['graph'] = True
        configopts['outmodes'].append('graph')
        if args.graph != None:
            configopts['graphdir'] = args.graph
        else:
            configopts['graphdir'] = '.'

    if args.shellcode:
        configopts['inspectionmodes'].append('shellcode')

    if args.emuprofile:
        configopts['emuprofile'] = True

    if int(args.emuprofileoutsize) > 0 and int(args.emuprofileoutsize) <= 10240:
        configopts['emuprofileoutsize'] = int(args.emuprofileoutsize)

    if args.bpf:
        configopts['bpf'] = args.bpf
        nids.param('pcap_filter', configopts['bpf'])

    if args.killtcp:
        if configopts['livemode']: configopts['killtcp'] = True

    if args.colored:
        configopts['colored'] = True

    if args.verbose:
        configopts['verbose'] = True

    if args.linemode:
        configopts['linemode'] = True

    sys.stdout = sys.__stdout__

    if not configopts['inspectionmodes'] and not configopts['linemode']:
        configopts['linemode'] = True
        if configopts['verbose']:
            print '[DEBUG] Inspection requires one or more regex direction flags or shellcode detection enabled, none found!'
            print '[DEBUG] Fallback - linemode enabled'
            print

    if configopts['verbose']:
        dumpargsstats(configopts)

    try:
        nids.chksum_ctl([('0.0.0.0/0', False)])
        nids.param('scan_num_hosts', 0)

        nids.init()
        nids.register_ip(handleip)
        nids.register_udp(handleudp)
        nids.register_tcp(handletcp)

        if args.confirm:
            print '[+] Callback handlers registered. Press any key to continue...',
            try: input()
            except: pass
        else:
            print '[+] Callback handlers registered'

        print '[+] NIDS initialized, waiting for events...' ; print
        try: nids.run()
        except KeyboardInterrupt: exitwithstats()

    except nids.error, nx:
        print
        print '[-] NIDS error: %s' % nx
        print
        sys.exit(1)
#   except Exception, ex:
#       print
#       print '[-] Exception: %s' % ex
#       print
#       sys.exit(1)

    exitwithstats()

if __name__ == '__main__':
    main()

