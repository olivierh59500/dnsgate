#!/usr/bin/env python3
# tab-width:4
# pylint: disable=missing-docstring

# PUBLIC DOMAIN
# http://github.com/jkeogh/dnsgate
# "psl domain" is "Public Second Level Domain" extracted using https://publicsuffix.org/
__version__ = "0.0.1"

import click
import copy
import time
import glob
import hashlib
import sys
import os
import shutil
import requests
import tldextract
import pprint
from shutil import copyfileobj
from logdecorator import logdecorator as ld
LOG_LEVELS = ld.LOG_LEVELS

logger_quiet = ld.logmaker(output_format=ld.QUIET_FORMAT, name="logging_quiet", level=ld.LOG_LEVELS['INFO'])
logger_debug = ld.logmaker(output_format=ld.FORMAT, name="logging_debug", level=ld.LOG_LEVELS['DEBUG'])

# prevent @ld.log_prefix() on main() from printing when debug is off
if '--debug' not in sys.argv:
    ld.log_prefix_logger.logger.setLevel(LOG_LEVELS['DEBUG'] + 1)

CONFIG_DIRECTORY = '/etc/dnsgate'
CACHE_DIRECTORY = CONFIG_DIRECTORY + '/cache'
TLDEXTRACT_CACHE = CACHE_DIRECTORY + '/tldextract_cache'
CUSTOM_BLACKLIST = CONFIG_DIRECTORY + '/blacklist'
CUSTOM_WHITELIST = CONFIG_DIRECTORY + '/whitelist'
DEFAULT_OUTPUT_FILE = CONFIG_DIRECTORY + '/generated_blacklist'
DEFAULT_REMOTE_BLACKLISTS = ['http://winhelp2002.mvps.org/hosts.txt', 'http://someonewhocares.org/hosts/hosts']
DEFAULT_CACHE_EXPIRE = 3600 * 24  # 24 hours
TLD_EXTRACT = tldextract.TLDExtract(cache_file=TLDEXTRACT_CACHE)


def make_output_file_header(config_dict):
    configuration_string = '\n'.join(['#    ' + str(key) + ': ' + str(config_dict[key]) for key in config_dict.keys()])

    output_file_header = '#'*64 + '''\n#
# AUTOMATICALLY GENERATED BY dnsgate:
#    https://github.com/jakeogh/dnsgate\n#
# CHANGES WILL BE LOST ON THE NEXT RUN.\n#
# EDIT ''' + CUSTOM_BLACKLIST + ' or ' + \
    CUSTOM_WHITELIST + ' instead.\n#\n' + \
    '# Generated by:\n# ' + ' '.join(sys.argv) + \
    '\n#' + '\n# Configuration:\n'  + configuration_string + '\n#\n' + '#'*64 + '\n\n'


    return output_file_header.encode('utf8')


class Config():
    def __init__(self):
        self.cache_expire = DEFAULT_CACHE_EXPIRE

pass_config = click.make_pass_decorator(Config, ensure=True)

def eprint(*args, level, **kwargs):
    if click_debug:
        logger_debug.logger.debug(*args, **kwargs)
    else:
        if level == LOG_LEVELS['INFO']:
            logger_quiet.logger.info(*args, **kwargs)
        elif level >= LOG_LEVELS['WARNING']:
            logger_quiet.logger.warning(*args, **kwargs)

@ld.log_prefix()
def restart_dnsmasq_service():
    if os.path.lexists('/etc/init.d/dnsmasq'):
        os.system('/etc/init.d/dnsmasq restart 1>&2')
    else:
        os.system('systemctl restart dnsmasq 1>&2')  # untested
    return True

@ld.log_prefix()
def hash_str(string):
    assert isinstance(string, str)
    assert len(string) > 0
    return hashlib.sha1(string.encode('utf-8')).hexdigest()

def remove_comments_from_bytes(line):
    assert isinstance(line, bytes)
    uncommented_line = b''
    for char in line:
        char = bytes([char])
        if char != b'#':
            uncommented_line += char
        else:
            break
    return uncommented_line

@ld.log_prefix(show_args=False)
def group_by_tld(domains):
    eprint('Sorting domains by their subdomain and grouping by TLD.',
        level=LOG_LEVELS['INFO'])
    sorted_output = []
    reversed_domains = []
    for domain in domains:
        rev_domain = domain.split(b'.')
        rev_domain.reverse()
        reversed_domains.append(rev_domain)
    reversed_domains.sort() # sorting a list of lists by the tld
    for rev_domain in reversed_domains:
        rev_domain.reverse()
        sorted_output.append(b'.'.join(rev_domain))
    return sorted_output

def extract_psl_domain(domain):
    dom = TLD_EXTRACT(domain.decode('utf-8'))
    dom = dom.domain + '.' + dom.suffix
    return dom.encode('utf-8')

@ld.log_prefix(show_args=False)
def strip_to_psl(domains):
    '''This causes ad-serving domains to be blocked at their root domain.
    Otherwise the subdomain can be changed until the --url lists are updated.
    It does not make sense to use this flag if you are generating a /etc/hosts
    format file since the effect would be to block google.com and not
    *.google.com.'''
    eprint('Removing subdomains on %d domains.', len(domains),
        level=LOG_LEVELS['INFO'])
    domains_stripped = set()
    for line in domains:
        line = extract_psl_domain(line)
        domains_stripped.add(line)
    return domains_stripped

@ld.log_prefix()
def write_unique_line(line, file):
    try:
        with open(file, 'r+') as fh:
            if line not in fh:
                fh.write(line)
    except FileNotFoundError:
        with open(file, 'a') as fh:
            fh.write(line)

@ld.log_prefix()
def backup_file_if_exists(file_to_backup):
    timestamp = str(time.time())
    dest_file = file_to_backup.name + '.bak.' + timestamp
    try:
        with open(file_to_backup.name, 'r') as sf:
            with open(dest_file, 'x') as df:
                copyfileobj(sf, df)
    except FileNotFoundError:
        pass    # skip backup is file does not exist

@ld.log_prefix(show_args=False)
def validate_domain_list(domains):
    eprint('Validating %d domains.', len(domains), level=LOG_LEVELS['DEBUG'])
    valid_domains = set([])
    for hostname in domains:
        try:
            hostname = hostname.decode('utf-8')
            hostname = hostname.encode('idna').decode('ascii')
            valid_domains.add(hostname.encode('utf-8'))
        except Exception as e:
            logger_debug.logger.exception(e)
    return valid_domains

def dnsmasq_install_help(output_file):
    dnsmasq_config_line = '\"conf-file=' + output_file + '\"'
    print('    $ cp -vi /etc/dnsmasq.conf /etc/dnsmasq.conf.bak.' + str(time.time()), file=sys.stderr)
    print('    $ grep ' + dnsmasq_config_line + ' /etc/dnsmasq.conf || { echo '
        + dnsmasq_config_line + ' >> /etc/dnsmasq.conf ; }', file=sys.stderr)
    print('    $ /etc/init.d/dnsmasq restart', file=sys.stderr)
    quit(0)

def hosts_install_help(output_file):
    print('    $ mv -vi /etc/hosts /etc/hosts.default', file=sys.stderr)
    print('    $ cat /etc/hosts.default ' + output_file + ' > /etc/hosts', file=sys.stderr)
    quit(0)

@ld.log_prefix()
def custom_list_append(domain_file, idns):
    for idn in idns:
        eprint("attempting to append %s to %s", idn, domain_file, level=LOG_LEVELS['INFO'])
        eprint("idn: %s", idn, level=LOG_LEVELS['DEBUG'])
        hostname = idn.encode('idna').decode('ascii')
        eprint("appending hostname: %s to %s", hostname, domain_file, level=LOG_LEVELS['DEBUG'])
        line = hostname + '\n'
        write_unique_line(line, domain_file)

@ld.log_prefix()
def extract_domain_set_from_dnsgate_format_file(dnsgate_file):
    domains = set([])
    dnsgate_file = os.path.abspath(dnsgate_file)
    try:
        dnsgate_file_bytes = read_file_bytes(dnsgate_file)
    except Exception as e:
        logger_debug.logger.exception(e)
    else:
        lines = dnsgate_file_bytes.splitlines()
        for line in lines:
            line = line.strip()
            line = remove_comments_from_bytes(line)
            line = b'.'.join(list(filter(None, line.split(b'.')))) # ignore leading/trailing .
            if len(line) > 0:
                domains.add(line)
    return set(domains)

@ld.log_prefix()
def read_file_bytes(file):
    if os.path.isfile(file):
        with open(file, 'rb') as fh:
            file_bytes = fh.read()
        return file_bytes
    else:
        raise FileNotFoundError(file + ' does not exist.')

@ld.log_prefix()
def extract_domain_set_from_hosts_format_url_or_cached_copy(url, no_cache=False):
    unexpired_copy = get_newest_unexpired_cached_url_copy(url=url)
    if unexpired_copy:
        eprint("Using cached copy: %s", unexpired_copy, level=LOG_LEVELS['INFO'])
        unexpired_copy_bytes = read_file_bytes(unexpired_copy)
        assert isinstance(unexpired_copy_bytes, bytes)
        return extract_domain_set_from_hosts_format_bytes(unexpired_copy_bytes)
    else:
        return extract_domain_set_from_hosts_format_url(url, no_cache)

@ld.log_prefix()
def generate_cache_file_name(url):
    url_hash = hash_str(url)
    file_name = CACHE_DIRECTORY + '/' + url_hash + '_hosts'
    return file_name

@ld.log_prefix()
@pass_config
def get_newest_unexpired_cached_url_copy(config, url):
    newest_copy = get_matching_cached_file(url)
    if newest_copy:
        newest_copy_timestamp = os.stat(newest_copy).st_mtime
        expiration_timestamp = int(newest_copy_timestamp) + int(config.cache_expire)
        if expiration_timestamp > time.time():
            return newest_copy
        else:
            os.rename(newest_copy, newest_copy + '.expired')
            return False
    return False

@ld.log_prefix()
def get_matching_cached_file(url):
    name = generate_cache_file_name(url)
    matching_cached_file = glob.glob(name)
    if matching_cached_file:
        return matching_cached_file[0]
    else:
        return False

@ld.log_prefix()
def read_url_bytes(url, no_cache=False):
    eprint("GET: %s", url, level=LOG_LEVELS['DEBUG'])
    user_agent = 'Mozilla/5.0 (X11; Ubuntu; Linux x86_64; rv:24.0) Gecko/20100101 Firefox/24.0'
    try:
        raw_url_bytes = requests.get(url, headers={'User-Agent': user_agent}, allow_redirects=True,
            stream=False, timeout=15.500).content
    except Exception as e:
        logger_debug.logger.exception(e)
        return False
    if not no_cache:
        cache_index_file = CACHE_DIRECTORY + '/sha1_index'
        cache_file = generate_cache_file_name(url)
        with open(cache_file, 'xb') as fh:
            fh.write(raw_url_bytes)

        line_to_write = cache_file + ' ' + url + '\n'
        write_unique_line(line_to_write, cache_index_file)

    eprint("Returning %d bytes from %s", len(raw_url_bytes), url, level=LOG_LEVELS['DEBUG'])
    return raw_url_bytes

@ld.log_prefix(show_args=False)
def extract_domain_set_from_hosts_format_bytes(hosts_format_bytes):
    assert isinstance(hosts_format_bytes, bytes)
    domains = set()
    hosts_format_bytes_lines = hosts_format_bytes.split(b'\n')
    for line in hosts_format_bytes_lines:
        line = line.replace(b'\t', b' ')         # expand tabs
        line = b' '.join(line.split())           # collapse whitespace
        line = line.strip()
        line = remove_comments_from_bytes(line)
        if b' ' in line:                         # hosts format
            line = line.split(b' ')[1]           # get DNS name (the url's are in hosts 0.0.0.0 dom.com format)
            # pylint: disable=bad-builtin
            line = b'.'.join(list(filter(None, line.split(b'.'))))    # ignore leading/trailing .
            # pylint: enable=bad-builtin
            domains.add(line)
    return domains

@ld.log_prefix()
def extract_domain_set_from_hosts_format_url(url, no_cache=False):
    url_bytes = read_url_bytes(url, no_cache)
    domains = extract_domain_set_from_hosts_format_bytes(url_bytes)
    eprint("Domains in %s:%s", url, len(domains), level=LOG_LEVELS['DEBUG'])
    return domains

@ld.log_prefix(show_args=False)
def prune_redundant_rules(domains_combined):
    domains_combined_orig = copy.deepcopy(domains_combined) # need to iterate through _orig later
    for domain in domains_combined_orig:
        if b'.' in domain:
            domain_parts = domain.split(b'.')
            domain_parts.pop(0)
            parent_domain = b'.'.join(domain_parts)
            if parent_domain in domains_combined:
                eprint("removing: %s because it's parent domain: %s is already blocked", domain, parent_domain,
                    level=LOG_LEVELS['DEBUG'])
                domains_combined.remove(domain)
    return domains_combined


OUTPUT_FILE_HELP = '''output file (defaults to ''' + DEFAULT_OUTPUT_FILE + ')'
NOCLOBBER_HELP = '''do not overwrite existing output file'''
BACKUP_HELP = '''backup output file before overwriting'''
INSTALL_HELP_HELP = '''show commands to configure dnsmasq or /etc/hosts (does nothing else)'''
SOURCE_HELP = '''\b
blacklist(s) to get rules from. Must be used for each remote path. Defaults to:\n   dnsgate \\
''' + ' \\ \n'.join(['   --source {0}'.format(i) for i in DEFAULT_REMOTE_BLACKLISTS])

WHITELIST_HELP = '''\b
whitelists(s) defaults to:''' + CUSTOM_WHITELIST.replace(os.path.expanduser('~'), '~')
BLOCK_AT_PSL_HELP = '''
\b
strips subdomains, for example:
    analytics.google.com -> google.com
    Useful for dnsmasq if you are willing to maintain a --whitelist file
    for inadvertently blocked domains.'''
DEBUG_HELP = '''print debugging information to stderr'''
VERBOSE_HELP = '''print more information to stderr'''
SHOW_CONFIG_HELP = '''print config information to stderr'''
NO_CACHE_HELP = '''do not cache --url files as sha1(url) to ~/.dnsgate/cache/'''
CACHE_EXPIRE_HELP = '''seconds until a cached remote file is re-downloaded (defaults to 24 hours)'''
DEST_IP_HELP = '''IP to redirect blocked connections to (defaults to 127.0.0.1)'''
RESTART_DNSMASQ_HELP = '''Restart dnsmasq service (defaults to True, ignored if --mode hosts)'''
BLACKLIST_APPEND_HELP = '''Add domain to ''' + CUSTOM_BLACKLIST
WHITELIST_APPEND_HELP = '''Add domain to ''' + CUSTOM_WHITELIST

# https://github.com/mitsuhiko/click/issues/441
CONTEXT_SETTINGS = dict(help_option_names=['--help'], terminal_width=shutil.get_terminal_size((80, 20)).columns)
@click.command(context_settings=CONTEXT_SETTINGS)
# pylint: disable=C0326
# http://pylint-messages.wikidot.com/messages:c0326
@click.option('--mode',             is_flag=False, type=click.Choice(['dnsmasq', 'hosts']), default='dnsmasq')
@click.option('--block-at-psl',     is_flag=True,  help=BLOCK_AT_PSL_HELP)
@click.option('--restart-dnsmasq',  is_flag=True,  help=RESTART_DNSMASQ_HELP, default=True)
@click.option('--output-file',      is_flag=False, help=OUTPUT_FILE_HELP,
    type=click.File(mode='wb', atomic=True), default=DEFAULT_OUTPUT_FILE)
@click.option('--backup',           is_flag=True,  help=BACKUP_HELP)
@click.option('--noclobber',        is_flag=True,  help=NOCLOBBER_HELP)
@click.option('--blacklist-append', is_flag=False, help=BLACKLIST_APPEND_HELP, multiple=True, type=str)
@click.option('--whitelist-append', is_flag=False, help=WHITELIST_APPEND_HELP, multiple=True, type=str)
@click.option('--source',           is_flag=False, help=SOURCE_HELP, multiple=True, default=DEFAULT_REMOTE_BLACKLISTS)
@click.option('--no-cache',         is_flag=True,  help=NO_CACHE_HELP)
@click.option('--cache-expire',     is_flag=False, help=CACHE_EXPIRE_HELP, type=int, default=DEFAULT_CACHE_EXPIRE)
@click.option('--dest-ip',          is_flag=False, help=DEST_IP_HELP)
@click.option('--show-config',      is_flag=True,  help=SHOW_CONFIG_HELP)
@click.option('--install-help',     is_flag=True,  help=INSTALL_HELP_HELP)
@click.option('--debug',            is_flag=True,  help=DEBUG_HELP)
@click.option('--verbose',          is_flag=True,  help=VERBOSE_HELP)
# pylint: enable=C0326
@ld.log_prefix()
@pass_config
def dnsgate(config, mode, block_at_psl, restart_dnsmasq, output_file, backup, noclobber,
            blacklist_append, whitelist_append, source, no_cache, cache_expire,
            dest_ip, show_config, install_help, debug, verbose):
    """dnsgate combines, deduplicates, and optionally modifies local and remote DNS blacklists."""

    config_dict = {
        "mode": mode,
        "block_at_psl": block_at_psl,
        "restart_dnsmasq": restart_dnsmasq,
        "output_file": output_file.name,
        "backup": backup,
        "noclobber": noclobber,
        "blacklist_append": blacklist_append,
        "whitelist_append": whitelist_append,
        "source": source,
        "no_cache": no_cache,
        "dest_ip": dest_ip,
        "debug": debug,
        "show_config": show_config,
        "install_help": install_help,
        "debug": debug,
        "verbose": verbose
        }

    if show_config:
        pprint.pprint(config_dict, stream=sys.stderr)

    if not os.path.isdir(CACHE_DIRECTORY):
        os.makedirs(CACHE_DIRECTORY)

    config.cache_expire = cache_expire

    global click_debug
    click_debug = debug

    if not verbose and not debug:
        logger_debug.logger.setLevel(LOG_LEVELS['DEBUG'] + 1)
        logger_quiet.logger.setLevel(LOG_LEVELS['INFO'] + 1)

    if verbose and not debug:
        logger_quiet.logger.setLevel(LOG_LEVELS['INFO'])

    if debug:
        logger_debug.logger.setLevel(LOG_LEVELS['DEBUG'])
    else:
        logger_debug.logger.setLevel(LOG_LEVELS['INFO'])

    if os.path.isfile(output_file.name) and output_file.name != '/dev/stdout' and output_file.name != '<stdout>':
        if noclobber:
            logger_debug.logger.error("File '%s' exists. Refusing to overwrite since --noclobber was used. Exiting.",
                output_file.name)
            quit(1)

    eprint('Using output_file: %s', output_file.name, level=LOG_LEVELS['INFO'])

    if install_help:
        if mode == 'dnsmasq':
            dnsmasq_install_help(output_file.name)
        elif mode == 'hosts':
            hosts_install_help(output_file.name)

    if whitelist_append:
        custom_list_append(CUSTOM_WHITELIST, whitelist_append)

    if blacklist_append:
        custom_list_append(CUSTOM_BLACKLIST, blacklist_append)

    domains_whitelist = set()
    eprint("Reading whitelist: %s", str(CUSTOM_WHITELIST), level=LOG_LEVELS['INFO'])
    whitelist_file = os.path.abspath(CUSTOM_WHITELIST)
    domains_whitelist = domains_whitelist | extract_domain_set_from_dnsgate_format_file(whitelist_file)
    if domains_whitelist:
        eprint("%d domains from the whitelist.", len(domains_whitelist), level=LOG_LEVELS['DEBUG'])
        domains_whitelist = validate_domain_list(domains_whitelist)
        eprint('%d validated whitelist domains.', len(domains_whitelist), level=LOG_LEVELS['INFO'])

    domains_combined_orig = set()   # domains from all sources, combined
    eprint("Reading remote blacklist(s):\n%s", str(source), level=LOG_LEVELS['INFO'])
    for item in source:
        if item.startswith('http'):
            try:
                eprint("Trying http:// blacklist location: %s", item, level=LOG_LEVELS['DEBUG'])
                domains = extract_domain_set_from_hosts_format_url_or_cached_copy(item, no_cache)
                if domains:
                    domains_combined_orig = domains_combined_orig | domains # union
                    eprint("len(domains_combined_orig): %s",
                        len(domains_combined_orig), level=LOG_LEVELS['DEBUG'])
                else:
                    logger_debug.logger.error('Failed to get %s, skipping.', item)
                    continue
            except Exception as e:
                logger_debug.logger.error("Exception on blacklist url: %s", item)
                logger_debug.logger.exception(e)
        else:
            logger_debug.logger.error("%s must start with http:// or https://, skipping.", item)

    eprint("%d domains from remote blacklist(s).",
        len(domains_combined_orig), level=LOG_LEVELS['INFO'])

    if len(domains_combined_orig) == 0:
        logger_debug.logger.error("WARNING: 0 domains were retrieved from " +
            "remote sources, only the local " + CUSTOM_BLACKLIST +
            " will be used.")

    domains_combined_orig = validate_domain_list(domains_combined_orig)
    eprint('%d validated remote blacklisted domains.',
        len(domains_combined_orig), level=LOG_LEVELS['INFO'])

    domains_combined = copy.deepcopy(domains_combined_orig) # need to iterate through _orig later

    if block_at_psl and mode != 'hosts':
        domains_combined = strip_to_psl(domains_combined)
        eprint("%d blacklisted domains left after stripping to PSL domains.",
            len(domains_combined), level=LOG_LEVELS['INFO'])

        eprint("Subtracting %d whitelisted domains.",
            len(domains_whitelist), level=LOG_LEVELS['INFO'])
        domains_combined = domains_combined - domains_whitelist
        eprint("%d blacklisted domains left after subtracting the whitelist.",
            len(domains_combined), level=LOG_LEVELS['INFO'])

        eprint('Iterating through the original %d whitelisted domains and ' +
            'making sure none are blocked by * rules.',
            len(domains_whitelist), level=LOG_LEVELS['INFO'])

        for domain in domains_whitelist:
            domain_psl = extract_psl_domain(domain)
            if domain_psl in domains_combined:
                domains_combined.remove(domain_psl)

        eprint('Iterating through original %d blacklisted domains to re-add subdomains' +
            ' that are not whitelisted', len(domains_combined_orig), level=LOG_LEVELS['INFO'])
        # re-add subdomains that are not explicitly whitelisted or already blocked
        for orig_domain in domains_combined_orig: # check every original full hostname
            if orig_domain not in domains_whitelist: # if it's not in the whitelist
                if orig_domain not in domains_combined: # and it's not in the current blacklist
                                                        # (almost none will be if --block-at-psl)
                    orig_domain_psl = extract_psl_domain(orig_domain)   # get it's psl to see if it's already blocked

                    if orig_domain_psl not in domains_combined: # if the psl is not already blocked
                        eprint("Re-adding: %s", orig_domain, level=LOG_LEVELS['DEBUG'])
                        domains_combined.add(orig_domain) # add the full hostname to the blacklist

        eprint('%d blacklisted domains after re-adding non-explicitly blacklisted subdomains',
            len(domains_combined), level=LOG_LEVELS['INFO'])

    elif block_at_psl and mode == 'hosts':
        logger_debug.logger.error("ERROR: --block-at-psl is not possible in hosts mode. Exiting.")
        quit(1)

    # apply whitelist before applying local blacklist
    domains_combined = domains_combined - domains_whitelist  # remove exact whitelist matches
    eprint("%d blacklisted domains after subtracting the %d whitelisted domains",
        len(domains_combined), len(domains_whitelist), level=LOG_LEVELS['INFO'])

    # must happen after subdomain stripping and after whitelist subtraction
    blacklist_file = os.path.abspath(CUSTOM_BLACKLIST)
    domains = extract_domain_set_from_dnsgate_format_file(blacklist_file)
    if domains:
        eprint("Got %s domains from the CUSTOM_BLACKLIST: %s",
            domains, blacklist_file, level=LOG_LEVELS['DEBUG'])
        eprint("Re-adding %d domains in the local blacklist %s to override the whitelist.",
            len(domains), CUSTOM_BLACKLIST, level=LOG_LEVELS['INFO'])
        domains_combined = domains_combined | domains # union
    eprint("%d blacklisted domains after re-adding the custom blacklist.",
        len(domains_combined), level=LOG_LEVELS['INFO'])

    eprint("Validating final domain block list.", level=LOG_LEVELS['DEBUG'])
    domains_combined = validate_domain_list(domains_combined)
    eprint('%d validated blacklisted domains.', len(domains_combined),
        level=LOG_LEVELS['DEBUG'])

    domains_combined = prune_redundant_rules(domains_combined)
    eprint('%d balcklisted domains after removing redundant rules.', len(domains_combined),
        level=LOG_LEVELS['INFO'])

    domains_combined = group_by_tld(domains_combined) # do last, returns sorted list
    eprint('Final blacklisted domain count: %d', len(domains_combined),
        level=LOG_LEVELS['INFO'])

    if backup: # todo: unit test
        backup_file_if_exists(output_file)

    try:
        os.mkdir(CONFIG_DIRECTORY)
    except FileExistsError:
        pass

    if not domains_combined:
        logger_debug.logger.error("The list of domains to block is empty, nothing to do, exiting.")
        quit(1)

    for domain in domains_whitelist:
        domain_tld = extract_psl_domain(domain)
        if domain_tld in domains_combined:
            eprint('%s is listed in both %s and %s, the local blacklist always takes precedence.',
                domain.decode('UTF8'), CUSTOM_BLACKLIST, CUSTOM_WHITELIST, level=LOG_LEVELS['WARNING'])

    eprint("Writing output file: %s in %s format", output_file.name, mode,
        level=LOG_LEVELS['INFO'])

    output_file.write(make_output_file_header(config_dict))

    for domain in domains_combined:
        if mode == 'dnsmasq':
            if dest_ip:
                dnsmasq_line = b'address=/.' + domain + b'/' + dest_ip + b'\n'
            else:
                dnsmasq_line = b'server=/.' + domain + b'/' b'\n'  # return NXDOMAIN
            output_file.write(dnsmasq_line)
        elif mode == 'hosts':
            if dest_ip:
                hosts_line = dest_ip + b' ' + domain + b'\n'
            else:
                hosts_line = b'127.0.0.1' + b' ' + domain + b'\n'
            output_file.write(hosts_line)

    output_file.close() # make sure file is written before restarting dnsmasq

    if restart_dnsmasq:
        if mode != 'hosts':
            restart_dnsmasq_service()

if __name__ == '__main__':
    # pylint: disable=no-value-for-parameter
    dnsgate()
    # pylint: enable=no-value-for-parameter
    eprint("Exiting without error.", level=LOG_LEVELS['DEBUG'])
    quit(0)
