###
# Copyright (c) 2014, James Lu
# All rights reserved.
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
#   * Redistributions of source code must retain the above copyright notice,
#     this list of conditions, and the following disclaimer.
#   * Redistributions in binary form must reproduce the above copyright notice,
#     this list of conditions, and the following disclaimer in the
#     documentation and/or other materials provided with the distribution.
#   * Neither the name of the author of this software nor the name of
#     contributors to this software may be used to endorse or promote products
#     derived from this software without specific prior written consent.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
# ARE DISCLAIMED.  IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
# LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
# CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
# SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
# INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
# CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
# ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
# POSSIBILITY OF SUCH DAMAGE.

###

from __future__ import unicode_literals
import supybot.utils as utils
from supybot.commands import *
import supybot.plugins as plugins
import supybot.ircutils as ircutils
import supybot.callbacks as callbacks
from collections import OrderedDict, defaultdict
try: # Python 3
    from urllib.parse import urlencode, quote
except ImportError: # Python 2
    from urllib import urlencode, quote
import json

# I don't want to be too dependant on BeautifulSoup at this time;
# not all commands use it, but it is required by some. -GLolol
global bs4Present
try:
    from bs4 import BeautifulSoup
except ImportError:
    bs4Present = False
else:
    bs4Present = True

try:
    from supybot.i18n import PluginInternationalization
    _ = PluginInternationalization('PkgInfo')
except ImportError:
    # Placeholder that allows to run the plugin on a bot
    # without the i18n module
    _ = lambda x:x

class PkgInfo(callbacks.Plugin):
    """Fetches package information from the repositories of
    Debian, Arch Linux, and Ubuntu."""
    threaded = True

    def __init__(self, irc):
        self.__parent = super(PkgInfo, self)
        self.__parent.__init__(irc)
        self.addrs = {'ubuntu':'http://packages.ubuntu.com/',
                      'debian':"https://packages.debian.org/"}

    def _getDistro(self, release):
        """<release>

        Guesses the distribution from the release name."""
        release = release.lower()
        if release.startswith(("oldstable","squeeze","wheezy","stable",
            "jessie","testing","sid","unstable")):
            distro = "debian"
        elif release.startswith(("hardy","lucid","maverick","natty","oneiric",
            "precise","quantal","raring","saucy","trusty","utopic","vivid")):
            distro = "ubuntu"
        else:
            distro = None
        return distro

    def MadisonParse(self, pkg, dist, codenames='', suite='', useSource=False, reverse=False):
        # The arch value implies 'all' (architecture-independent packages) and 'source'
        # (source packages), in order to prevent misleading "Not found" errors.
        arch = self.registryValue("archs") + ['all', 'source']
        arch = ','.join(set(arch))
        self.arg = {'package':pkg,'table':dist,'a':arch,'c':codenames,'s':suite,
            }
        if useSource:
            self.arg['S'] = 'on'
        self.arg = urlencode(self.arg)
        url = 'https://qa.debian.org/madison.php?text=on&' + self.arg
        d = OrderedDict()
        fd = utils.web.getUrlFd(url)
        for line in fd.readlines():
            L = line.decode("utf-8").split("|")
            L = list(map(str.strip, list(map(str, L))))
            if useSource:
                d['%s: %s' % (L[2], L[0])] = (L[1], L[3])
            else:
                d[L[2]] = (L[1],L[3])
        if d:
            if reverse:
                # *sigh*... I wish there was a better way to do this
                d = OrderedDict(reversed(tuple(d.items())))
            if self.registryValue("verbose"):
                return 'Found %s results: ' % len(d) + ', '.join("{!s} " \
                "\x02({!s} [{!s}])\x02".format(k,v[0],v[1]) for (k,v) in \
                d.items())
            return 'Found %s results: ' % len(d) + ', '.join("{!s} " \
            "\x02({!s})\x02".format(k,v[0]) for (k,v) in d.items())
        else:
            self.log.debug("PkgInfo: No results found for URL %s" % url)

    def package(self, irc, msg, args, release, pkg):
        """<release> <package>

        Fetches information for <package> from Debian or Ubuntu's repositories.
        <release> is the codename/release name (e.g. 'trusty', 'squeeze').
        For Arch Linux packages, please use 'archpkg' and 'archaur' instead."""
        if not bs4Present:
            irc.error("This command requires the Beautiful Soup 4 library. See"
                " https://github.com/GLolol/SupyPlugins/blob/master/README.md"
                "#pkginfo for instructions on how to install it.", Raise=True)
        pkg = pkg.lower()
        distro = self._getDistro(release)
        try:
            url = self.addrs[distro] + "{}/{}".format(release, pkg)
        except KeyError:
            irc.error('Unknown distribution.', Raise=True)
        try:
            fd = utils.web.getUrl(url).decode("utf-8")
        except utils.web.Error as e:
            irc.error(str(e), Raise=True)
        soup = BeautifulSoup(fd)
        if "Error" in soup.title.string:
            err = soup.find('div', attrs={"id":"content"}).find('p').string
            if "two or more packages specified" in err:
                irc.error("Unknown distribution/release.", Raise=True)
            irc.reply(err)
            return
        desc = soup.find('meta', attrs={"name":"Description"})["content"]
        # Get package information from the meta tags
        keywords = soup.find('meta', attrs={"name":"Keywords"})["content"]
        keywords = keywords.replace(",","").split()
        irc.reply("Package: \x02{} ({})\x02 in {} - {}; View more at: {}".format(pkg,
        keywords[-1], keywords[1], desc, url))
    pkg = wrap(package, ['somethingWithoutSpaces', 'somethingWithoutSpaces'])

    def vlist(self, irc, msg, args, distro, pkg, opts):
        """<distribution> <package> [--source] [--reverse(d)]

        Fetches all available version of <package> in <distribution>, if
        such package exists. Supported entries for <distribution>
        include 'debian', 'ubuntu', 'derivatives', and 'all'. If
        --source is given, search for packages by source package
        name. If --reverse or --reversed is given, show the newest package versions
        first."""
        pkg, distro = map(str.lower, (pkg, distro))
        supported = ("debian", "ubuntu", "derivatives", "all")
        if distro not in supported:
            distro = self._getDistro(distro)
            if distro is None:
                irc.error("Unknown distribution.", Raise=True)
        opts = dict(opts)
        reverse = 'reverse' in opts or 'reversed' in opts
        d = self.MadisonParse(pkg, distro, useSource='source' in opts, reverse=reverse)
        if not d: irc.error("No results found.",Raise=True)
        try:
            d += " View more at: {}search?keywords={}".format(self.addrs[distro], pkg)
        except KeyError:
            pass
        irc.reply(d)
    vlist = wrap(vlist, ['somethingWithoutSpaces', 'somethingWithoutSpaces', getopts({'source':'',
        'reverse':'','reversed':''})])

    def archpkg(self, irc, msg, args, pkg, opts):
        """<package> [--exact]

        Looks up <package> in the Arch Linux package repositories.
        If --exact is given, will output only exact matches.
        """
        pkg = pkg.lower()
        baseurl = 'https://www.archlinux.org/packages/search/json/?'
        if 'exact' in dict(opts):
            fd = utils.web.getUrl(baseurl + urlencode({'name':pkg}))
        else:
            fd = utils.web.getUrl(baseurl + urlencode({'q':pkg}))
        data = json.loads(fd.decode("utf-8"))
        if data['valid'] and data['results']:
            f = set()
            archs = defaultdict(list)
            for x in data['results']:
                s = "{} - {} \x02({})\x02".format(x['pkgname'],x['pkgdesc'],x['pkgver'])
                f.add(s)
                archs[s].append(x['arch'])
            count = len(f)
            if self.registryValue("verbose"):
                irc.reply('Found %s results: ' % count + ', ' \
                .join("{} \x02[{!s}]\x02".format(s, ', '.join(archs[s])) for s in f))
            else:
                irc.reply('Found {} results: {}'.format(count,', '.join(f)))
        else: irc.error("No results found.",Raise=True)
    archpkg = wrap(archpkg, ['somethingWithoutSpaces', getopts({'exact':''})])

    def archaur(self, irc, msg, args, pkg):
        """<package>

        Looks up <package> in the Arch Linux AUR."""
        pkg = pkg.lower()
        baseurl = 'https://aur.archlinux.org/rpc.php?type=search&'
        fd = utils.web.getUrl(baseurl + urlencode({'arg':pkg}))
        data = json.loads(fd.decode("utf-8"))
        if data["type"] == "error":
            irc.error(data["results"], Raise=True)
        count = data["resultcount"]
        if count:
            # We want this to be limited to prevent overflow warnings
            # in the bot.
            if count > 150:
                count = '150+'
            s = "Found {} result{}: ".format(count,
                's' if data["resultcount"] != 1 else '')
            for x in data['results'][:150]:
                verboseInfo = ''
                if self.registryValue("verbose"):
                    verboseInfo = " [ID:{} Votes:{}]".format(x['ID'], x['NumVotes'])
                s += "{} - {} \x02({}{})\x02, ".format(x['Name'],x['Description'],x['Version'], verboseInfo)
            irc.reply(s[:-2]) # cut off the ", " at the end
        else:
            irc.error("No results found.", Raise=True)
    archaur = wrap(archaur, ['somethingWithoutSpaces'])

    def pkgsearch(self, irc, msg, args, distro, query):
        """<distro> <query>

        Looks up <query> in <distro>'s website (for Debian/Ubuntu)."""
        if not bs4Present:
            irc.error("This command requires the Beautiful Soup 4 library. See"
                " https://github.com/GLolol/SupyPlugins/blob/master/README.md"
                "#pkginfo for instructions on how to install it.", Raise=True)
        distro = distro.lower()
        if distro not in ("debian", "ubuntu"):
            distro = self._getDistro(distro)
        try:
            url = '%ssearch?keywords=%s' % (self.addrs[distro], quote(query))
        except KeyError:
            irc.error('Unknown distribution.', Raise=True)
        try:
            fd = utils.web.getUrl(url).decode("utf-8")
        except utils.web.Error as e:
            irc.error(str(e), Raise=True)
        soup = BeautifulSoup(fd)
        # Debian/Ubuntu use h3 for result names in the format 'Package abcd'
        results = [pkg.string.split()[1] for pkg in soup.find_all('h3')]
        if results:
            s = "Found %s results: \x02%s\x02; View more at %s" % (len(results),
                utils.str.commaAndify(results), url)
            irc.reply(s)
        else:
            e = "No results found."
            try:
                if distro == "debian":
                    errorParse = soup.find("div", class_="note").p
                else:
                    errorParse = soup.find("p", attrs={"id": "psearchtoomanyhits"})
                if errorParse:
                    for br in errorParse.findAll('br'):
                        br.replace_with(" ")
                    e = errorParse.text.strip()
            except AttributeError:
                pass
            irc.error(e)
    pkgsearch = wrap(pkgsearch, ['somethingWithoutSpaces', 'somethingWithoutSpaces'])

    def mintpkg(self, irc, msg, args, release, query, opts):
        """<release> <package> [--exact]

        Looks up <package> in Linux Mint's repositories."""
        if not bs4Present:
            irc.error("This command requires the Beautiful Soup 4 library. See"
                " https://github.com/GLolol/SupyPlugins/blob/master/README.md"
                "#pkginfo for instructions on how to install it.", Raise=True)
        addr = 'http://packages.linuxmint.com/list.php?release=' + quote(release)
        try:
            fd = utils.web.getUrl(addr).decode("utf-8")
        except utils.web.Error as e:
            irc.error(str(e), Raise=True)
        soup = BeautifulSoup(fd)
        # Linux Mint puts their package lists in tables
        results = soup.find_all("td")
        found = OrderedDict()
        query = query.lower()
        exact = 'exact' in dict(opts)
        for result in results:
            name = result.contents[0].string # Package name
            if query == name or (query in name and not exact):
                # This feels like really messy code, but we have to find tags
                # relative to our results.
                # Ascend to find the section name (in <h2>):
                section = result.parent.parent.parent.previous_sibling.\
                    previous_sibling.string
                # Find the package version in the next <td>; for some reason we have
                # to go two siblings further, as the first .next_sibling returns '\n'.
                # This is mentioned briefly in Beautiful Soup 4's documentation...
                version = result.next_sibling.next_sibling.string
                found['%s [\x02%s\x02]' % (name, section)] = version
        if found:
            s = 'Found %s results: ' % len(found)
            for x in found:
                s += '%s \x02(%s)\x02, ' % (x, found[x])
            s += 'View more at: %s' % addr
            irc.reply(s)
        else:
            irc.error('No results found.')
    mintpkg = wrap(mintpkg, ['somethingWithoutSpaces', 'somethingWithoutSpaces',
        getopts({'exact':''})])

Class = PkgInfo


# vim:set shiftwidth=4 softtabstop=4 expandtab textwidth=79:
