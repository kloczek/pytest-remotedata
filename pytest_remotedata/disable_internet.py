# Licensed under a 3-clause BSD style license - see LICENSE.rst
import contextlib
import socket
import urllib.request

# save original socket method for restoration
# These are global so that re-calling the turn_off_internet function doesn't
# overwrite them again
socket_original = socket.socket
socket_create_connection = socket.create_connection
socket_bind = socket.socket.bind
socket_connect = socket.socket.connect

GITHUB_HOSTS = ['www.github.io']
ASTROPY_HOSTS = (['data.astropy.org', 'astropy.stsci.edu', 'www.astropy.org'] +
                 GITHUB_HOSTS)

INTERNET_OFF = False

# urllib2 uses a global variable to cache its default "opener" for opening
# connections for various protocols; we store it off here so we can restore to
# the default after re-enabling internet use
_orig_opener = None


def _resolve_host_ips(hostname, port=80):
    """
    Obtain all the IPs, including aliases, in a way that supports
    IPv4/v6 dual stack.
    """
    try:
        ips = {s[-1][0] for s in socket.getaddrinfo(hostname, port)}
    except socket.gaierror:
        ips = set()

    ips.add(hostname)
    return ips


# ::1 is apparently another valid name for localhost?
# it is returned by getaddrinfo when that function is given localhost

def check_internet_off(original_function, allow_astropy_data=False,
                       allow_github_data=False):
    """
    Wraps ``original_function``, which in most cases is assumed
    to be a `socket.socket` method, to raise an `IOError` for any operations
    on non-local AF_INET sockets.

    Allowing Astropy data also automatically allow GitHub data.
    """

    def new_function(*args, **kwargs):
        if isinstance(args[0], socket.socket):
            if not args[0].family in (socket.AF_INET, socket.AF_INET6):
                # Should be fine in all but some very obscure cases
                # More to the point, we don't want to affect AF_UNIX
                # sockets.
                return original_function(*args, **kwargs)
            host = args[1][0]
            addr_arg = 1
            valid_hosts = {'localhost', '127.0.0.1', '::1'}
        else:
            # The only other function this is used to wrap currently is
            # socket.create_connection, which should be passed a 2-tuple, but
            # we'll check just in case
            if not (isinstance(args[0], tuple) and len(args[0]) == 2):
                return original_function(*args, **kwargs)

            host = args[0][0]
            addr_arg = 0
            valid_hosts = {'localhost', '127.0.0.1'}

        # Astropy + GitHub data
        if allow_astropy_data:
            for valid_host in ASTROPY_HOSTS:
                valid_hosts = valid_hosts.union(_resolve_host_ips(valid_host))

        # Only GitHub data
        elif allow_github_data:
            for valid_host in GITHUB_HOSTS:
                valid_hosts = valid_hosts.union(_resolve_host_ips(valid_host))

        hostname = socket.gethostname()
        fqdn = socket.getfqdn()

        if host in (hostname, fqdn):
            host = 'localhost'
            host_ips = {host}
            new_addr = (host, args[addr_arg][1])
            args = args[:addr_arg] + (new_addr,) + args[addr_arg + 1:]
        else:
            host_ips = _resolve_host_ips(host)

        if len(host_ips & valid_hosts) > 0:  # Any overlap is acceptable
            return original_function(*args, **kwargs)
        else:
            raise OSError("An attempt was made to connect to the internet "
                          "by a test that was not marked `remote_data`. The "
                          "requested host was: {}".format(host))
    return new_function


def turn_off_internet(verbose=False, allow_astropy_data=False,
                      allow_github_data=False):
    """
    Disable internet access via python by preventing connections from being
    created using the socket module.  Presumably this could be worked around by
    using some other means of accessing the internet, but all default python
    modules (urllib, requests, etc.) use socket [citation needed].
    """

    global INTERNET_OFF
    global _orig_opener

    if INTERNET_OFF:
        return

    INTERNET_OFF = True

    __tracebackhide__ = True
    if verbose:
        print("Internet access disabled")

    # Update urllib2 to force it not to use any proxies
    # Must use {} here (the default of None will kick off an automatic search
    # for proxies)
    _orig_opener = urllib.request.build_opener()
    no_proxy_handler = urllib.request.ProxyHandler({})
    opener = urllib.request.build_opener(no_proxy_handler)
    urllib.request.install_opener(opener)

    socket.create_connection = check_internet_off(
        socket_create_connection, allow_astropy_data=allow_astropy_data,
        allow_github_data=allow_github_data)
    socket.socket.bind = check_internet_off(
        socket_bind, allow_astropy_data=allow_astropy_data,
        allow_github_data=allow_github_data)
    socket.socket.connect = check_internet_off(
        socket_connect, allow_astropy_data=allow_astropy_data,
        allow_github_data=allow_github_data)

    return socket


def turn_on_internet(verbose=False):
    """
    Restore internet access.  Not used, but kept in case it is needed.
    """

    global INTERNET_OFF
    global _orig_opener

    if not INTERNET_OFF:
        return

    INTERNET_OFF = False

    if verbose:
        print("Internet access enabled")

    urllib.request.install_opener(_orig_opener)

    socket.create_connection = socket_create_connection
    socket.socket.bind = socket_bind
    socket.socket.connect = socket_connect
    return socket


@contextlib.contextmanager
def no_internet(verbose=False):
    """Context manager to temporarily disable internet access (if not already
    disabled).  If it was already disabled before entering the context manager
    (i.e. `turn_off_internet` was called previously) then this is a no-op and
    leaves internet access disabled until a manual call to `turn_on_internet`.
    """

    already_disabled = INTERNET_OFF

    turn_off_internet(verbose=verbose)
    try:
        yield
    finally:
        if not already_disabled:
            turn_on_internet(verbose=verbose)
