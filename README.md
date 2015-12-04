
# dnsgate

**dnsgate** merges 3rd party [1] DNS blocking lists into `/etc/dnsmasq.conf` or `/etc/hosts` format.

While not required, [dnsmasq](https://wiki.gentoo.org/wiki/Dnsmasq) improves on conventional [/etc/hosts domain blocking](http://winhelp2002.mvps.org/hosts.htm) by enabling * blocking of domains.

For example *.google.com:

```
echo 'address=/.google.com/127.0.0.1' >> /etc/dnsmasq.conf
```
Has the effect of returning 127.0.0.1 for all google.com domains. Rather than return 127.0.0.1, dnsmasq can be configured to return NXDOMAIN:

```
echo 'server=/.google.com/' >> /etc/dnsmasq.conf
```
This instead returns NXDOMAIN, which is dnsgate's default behavior in dnsmasq mode.

Said another way, conventional `/etc/hosts` blocking can't use wildcards (*) and therefore requires the user to keep track of each subdomain / domain combination they want to block. This is not necessarily a problem. Even if you don't use dnsmasq, other people [1] keep track of the subdomains for you. If you want to block a specific domain completely, use dnsmasq.

With `--mode dnsmasq` (default if not specified) the `--block-at-tld` option strips domains to their TLD, removing the need to manually specify/track specific subdomains. `--block-at-tld` may block TLD's you want to use, so use it with `--whitelist`.

**Features**

* **Wildcard Blocking** Optionally block full TLD's instead of individual subdomains (dnsmasq mode only).
* **System-wide.** All programs that use the local DNS resolver benefit. 
* **Non-interactive.** Can be run as a periodic cron job.
* **Fully Configurable.** See ./dnsgate --help (TODO, add /etc/dnsgate/config file support)
* **Custom Lists.** Use /etc/dnsgate/blacklist and /etc/dnsgate/whitelist.
* **Return NXDOMAIN** Rather than redirect the request to 127.0.0.1, NXDOMAIN is returned. (dnsmasq mode only).
* **Return Custom IP** --dest-ip allows redirection to specified IP (disables returning NXDOMAIN in dnsmasq mode)
* **Installation Support** see --install-help
* **Extensive Debugging Support.** see --verbose and --debug
* **IDN Support** What to block snowman? ./dnsgate --blacklist-append ☃.net

**Features TODO**
* **Downloaded list caching** Optionally cache and re-use downloaded blacklists instead of re-fetching each time (configurable timeout, see --cache-timeout) (partially done).
* **Full test coverage**
* **Fully-interactive.** Can be run as an interactive wizard. See --interactive (TODO).

**Dependencies**
 - python3.x
 - [click](https://github.com/mitsuhiko/click)
 - [tldextract](https://github.com/john-kurkowski/tldextract)
 - [colorama](https://github.com/tartley/colorama)

```
Usage: dnsgate [OPTIONS]

Options:
  --mode [dnsmasq|hosts]
  --block-at-tld          
                           strips subdomains, for example:
                               analytics.google.com -> google.com
                               Useful for dnsmasq if you are willing to maintain a --whitelist file
                               for inadvertently blocked domains.
  --restart-dnsmasq        Restart dnsmasq service (defaults to True, ignored if --mode hosts)
  --output-file TEXT       output file defaults to /etc/dnsgate/generated_blacklist
  --backup                 backup output file before overwriting
  --noclobber              do not overwrite existing output file
  --blacklist-append TEXT  Add domain to /etc/dnsgate/blacklist
  --whitelist-append TEXT  Add domain to /etc/dnsgate/whitelist
  --blacklist TEXT        
                           blacklist(s) defaults to:
                               http://winhelp2002.mvps.org/hosts.txt
                               http://someonewhocares.org/hosts/hosts
                               /etc/dnsgate/blacklist
  --whitelist TEXT        
                           whitelists(s) defaults to:/etc/dnsgate/whitelist
  --cache                  cache --url files as dnsgate_cache_domain_hosts.(timestamp) to ~/.dnsgate/cache
  --dest-ip TEXT           IP to redirect blocked connections to (defaults to 127.0.0.1)
  --show-config            print config information to stderr
  --install-help           show commands to configure dnsmasq or /etc/hosts (note: this does nothing else)
  --debug                  print debugging information to stderr
  --help                   Show this message and exit.
```
 
**dnsmasq example:**
 
```  
$ ./dnsgate
 * Stopping dnsmasq ... [ ok ]
 * Starting dnsmasq ... [ ok ]
  
$ ./dnsgate --install-help
    $ cp -vi /etc/dnsmasq.conf /etc/dnsmasq.conf.bak.1449189491.404291
    $ grep "conf-file=/etc/dnsgate/generated_blacklist" /etc/dnsmasq.conf || { echo "conf-file=/etc/dnsgate/generated_blacklist" >> /etc/dnsmasq.conf ; }
    $ /etc/init.d/dnsmasq restart
``` 
**is equivalent to:**
 
```  
$ ./dnsgate --show-config
mode: dnsmasq
block_at_tld: False
restart_dnsmasq: True
output_file: /etc/dnsgate/generated_blacklist
backup: False
noclobber: False
blacklist_append: None
whitelist_append: None
blacklist: ['http://winhelp2002.mvps.org/hosts.txt', 'http://someonewhocares.org/hosts/hosts', '/etc/dnsgate/blacklist']
whitelist: ['/etc/dnsgate/whitelist']
cache: False
dest_ip: None
debug: False
show_config: True
install_help: False
debug: False
 * Stopping dnsmasq ... [ ok ]
 * Starting dnsmasq ... [ ok ]
``` 
**hosts example:**
 
```  
$ ./dnsgate --mode hosts
  
$ ./dnsgate --mode hosts --install-help
    $ mv -vi /etc/hosts /etc/hosts.default
    $ cat /etc/hosts.default /etc/dnsgate/generated_blacklist > /etc/hosts
``` 
**is equivalent to:**
 
```  
$ ./dnsgate --mode hosts --show-config
mode: hosts
block_at_tld: False
restart_dnsmasq: True
output_file: /etc/dnsgate/generated_blacklist
backup: False
noclobber: False
blacklist_append: None
whitelist_append: None
blacklist: ['http://winhelp2002.mvps.org/hosts.txt', 'http://someonewhocares.org/hosts/hosts', '/etc/dnsgate/blacklist']
whitelist: ['/etc/dnsgate/whitelist']
cache: False
dest_ip: None
debug: False
show_config: True
install_help: False
debug: False
``` 

`[1]:`
 `http://winhelp2002.mvps.org/hosts.txt`
 `http://someonewhocares.org/hosts/hosts`


**More Information**

 - https://news.ycombinator.com/item?id=10572700
 - https://news.ycombinator.com/item?id=10369516

**Related Software**

 - https://github.com/gaenserich/hostsblock (bash)
 - http://pgl.yoyo.org/as/#unbound
 - https://github.com/longsleep/adblockrouter
 - https://github.com/StevenBlack/hosts (TODO, use this)  

**Simple Software**

If you find this useful you may appreciate:

 - Disabling JS and making a keybinding to enable it ([surf](http://surf.suckless.org/)+[tabbed](http://tools.suckless.org/tabbed/) makes this easy)
 - [musl](http://wiki.musl-libc.org/wiki/Functional_differences_from_glibc#Name_Resolver_.2F_DNS)


