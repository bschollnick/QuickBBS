'''
Created on 2013-02-09

@author: jdcumpson
@author: Noobie
@copyright: (c) JD Cumpson 2013.
'''

import pybonjour
from twisted.python import log
from twisted.internet import reactor, defer
from twisted.internet.protocol import Protocol
from zope import interface

from txbonjour.service import (BonjourService, BonjourReader,
                               IBroadcastProtocol, IDiscoverProtocol)


class BroadcastProtocol(Protocol):
    
    interface.implements(IBroadcastProtocol)

    def logPrefix(self):
        return self.__class__.__name__

    def registerReceived(self, service):
        """Override in sub-classes."""
        
    def connectionMade(self):
        """Override in sub-classes."""
        
    def connectionLost(self, reason=None):
        """Override in sub-classes."""


class DiscoverProtocol(Protocol):
    
    interface.implements(IDiscoverProtocol)
    
    def browseError(self, error):
        """
        Override in sub-classes.
        """
        
    def resolveError(self, error):
        """
        Override in sub-classes.
        """
    
    def addService(self, service):
        """
        Override in sub-classes.
        """
        
    def removeService(self, service):
        """
        Override in sub-classes.
        """
    
    def connectionMade(self):
        """
        Override in sub-classes.
        """
        
    def connectionLost(self, reason=None):
        """
        Override in sub-classes.
        """


class BonjourServiceInformation(object):
    """ Represents a service that is available via the avahi/bonjour framework.
        The class provides a better way to get more details about a service as
        a convenience because there were too many variables being passed
        directly. This class makes it easier to group up information about the
        BonjourService.
    """

    resolved = False

    def __init__(self, name, registry_type, reply_domain,
                 flags, interface_index, sdref):
        self.name = name
        self.registry_type = registry_type
        self.reply_domain = reply_domain
        self.flags = flags
        self.interface_index = interface_index
        self.sdref = sdref
        self.ip = None
        self.port = None
        self.txt_record = None
        self.fullname = None
        self.lock = defer.DeferredLock()

    def resolve(self):
        if self.resolved:
            return defer.succeed(self)

        d = resolve(self.interface_index,
                    self.name,
                    self.registry_type,
                    self.reply_domain,
                    )
        def _update_properties(result):
            self.fullname, self.fqdn, self.port, self.txt_record = result
            self.resolved = True
            return self
            
        d.addCallback(_update_properties)
        return d

    def resolve_ip(self, resolve=True,):
        """ Resolve the ip address of this services FQDN. If resolve is True
            (default=True) then also resolve the service fully before trying
            to resolve the ip. Otherwise raises an exception.

        """
        if self.ip:
            return defer.succeed(self.ip)

        if not resolve and not self.resolved:
            return defer.fail(Exception('Cannot resolve an ip address of an unresolved service'))

        if self.resolved:
            d = defer.succeed(self)
        else:
            d = self.resolve()

        def _update_properties(result):
            self.ip = result
            return self.ip

        d.addCallback(lambda _: reactor.resolve(self.fqdn))
        d.addCallback(_update_properties)
        return d

    def __repr__(self):
        info = {
                'name': self.name,
                'registry': self.registry_type,
                'reply_domain': self.reply_domain,
                'resolved': self.resolved,
                'record': self.txt_record,
                'flags': self.flags,
                }

        if self.resolved:
            info['port'] = self.port
            if self.ip:
                info['ip'] = self.ip

        infostr = []
        for key, val in info.iteritems():
            if isinstance(val, (basestring,)):
                val = '"%s"' % (val,)
            infostr.append('%s=%s' % (key, val,))

        infostr = '(%s)' % (', '.join(infostr),)
        return '<%s %s>' % (self.__class__.__name__, infostr,)

    def __eq__(self, other):
        if not isinstance(other, self.__class__):
            return False
        properties = ('name', 'registry_type', 'reply_domain', 'flags',)
        try:
            for prop in properties:
                if getattr(self, prop) != getattr(other, prop):
                    return False
        except:
            return False

        return True

    def __neq__(self, other):
        return not self.__eq__(other)


def broadcast(protocol, regtype, port, name, record=None, _do_start=True):
    """
    Make a BonjourReader instance. A bonjour reader is just like a file 
    descriptor for read-only. It implements the twisted interface 
    'twisted.internet.interfaces.IReadDescriptor'. This service will
    watch the Bonjour output that corresponds to this service.
    
    XXX: this should probably actually disconnect readers in more of a one-off
         broadcast type message. ie. reader.stopReading() after finished. To
         be consistent with the behaviour of the discover method, it does not.

    @param protocol: A protocol implementing IBroadcastProtocl
    @param regtype: A string for the mDNS registry via pybonjour
    @param name: The name of your service
    @param port: The port that your service is listening on
    @param record: A pybonjour.TXTRecord instance (mDNS record)
    @param _do_start: if True, starts immediately.
    @return: a BonjourReader instance
    @rtype: txbonjour.service.BonjourReader
    
    @see: https://code.google.com/p/pybonjour/
    @see: http://http://twistedmatrix.com/documents/current/api/
            twisted.internet.interfaces.IReactorFDSet.html
    """
    # txt record can keep track of the mDNS changes
    if record is None:
        record = pybonjour.TXTRecord({})

    def cb(sdref, flags, interface_index, service_name, registry_type,
           reply_domain):
        info = BonjourServiceInformation(service_name,
                                         registry_type,
                                         reply_domain,
                                         flags,
                                         interface_index,
                                         sdref,)
        protocol.registerReceived(info)

    sdref = pybonjour.DNSServiceRegister(regtype=regtype,
                                         port=port,
                                         callBack=cb,
                                         txtRecord=record,
                                         name=name,
                                         )
    reader = BonjourReader(protocol, sdref)

    # if true start reading immediately
    if _do_start:
        reader.startReading()

    return reader


_registered_services = []


def discover(protocol, regtype, resolve=True, resolve_ips=False, _do_start=True):
    """
    Make a BonjourReader instance. This instance will monitor the Bonjour
    daemon and call the appropriate method on the protocol object when it is
    read from the service.
    
    @param protocol: A protocol implementing IDiscoverProtocol
    @param regtype: A string for the mDNS registry via pybonjour
    @param resolve: Resolve the avahi/bonjour service details automatically
                    (default=True)
    @param resolve_ips: Resolve FQDN to ip address automatically (default=False)
    @param _do_start: if True, starts immediately
    @returns: A BonjourReader instance
    @rtype: txbonjour.service.BonjourReader
    """
    
    def _callback(sdref, flags, interface_index, error_code, service_name,
                  registry_type, reply_domain):
        
        # if there is an error code call it
        if error_code != pybonjour.kDNSServiceErr_NoError:
            err = pybonjour.BonjourError(error_code)
            protocol.browseError(err)
            return
        
        # create the service object
        info = BonjourServiceInformation(service_name,
                                         registry_type,
                                         reply_domain,
                                         flags,
                                         interface_index,
                                         sdref,)


        # try to find an equivalent service declaration and use it
        index = -1
        for n, s in enumerate(_registered_services):
            if info == s:
                index = n
                break

        # if an equivalent was found, use it instead
        if index > -1:
            info = _registered_services[index]

        # otherwise, add the new one to the list
        else:
            _registered_services.append(info)

        # logical and to determine if it was an addition or removal
        add_service = flags & pybonjour.kDNSServiceFlagsAdd

        def lock_acquired(_):
            action = 'add' if add_service else 'remove'
#             log.msg('%s service: %s' % (action, info,))

            # if we are removing a service we can't resolve it because it is no
            # longer available
            if not add_service:
                return info

            # resolve the ip of the service when it is resolved
            if resolve_ips:
#                 log.msg('resolving ip address for: %s' % (info,))
                return info.resolve_ip()

            # just resolve the service with the FQDN
            if resolve:
#                 log.msg('resolving service: %s' % (info,))
                d.addCallback(lambda _: info.resolve())

            return info

        # acquire the lock for this service (ensure sync'd add/remove)
        d = info.lock.acquire()
        d.addCallback(lock_acquired)

        def resolve_cb(result):
            if add_service:
                method = protocol.addService

            else:
                # remove the service from the list before calling back the proto
                _registered_services.remove(info)
                method = protocol.removeService

            # call it with the reader instance to make things cleaner
            log.callWithLogger(reader, method, info)

        d.addCallbacks(resolve_cb, lambda f: protocol.resolveError(f.value))
        d.addErrback(lambda f: protocol.browseError(f.value))
        d.addBoth(lambda _: info.lock.release())
        
    sdref = pybonjour.DNSServiceBrowse(regtype=regtype, callBack=_callback)
    reader = BonjourReader(protocol, sdref)
    return reader


def resolve(interface_index, service_name, registry_type, reply_domain,
            protocol=None):
    """ Resolve a service based on the interface index, service name,
        registry type, and reply domain. If you already have a BonjourService
        you should call BonjourService.resolve(). This method is for evaluating
        string based arguments.

        Typical use cases you will not need this method, but it is available
        to use if needed.
    """
    
    d = defer.Deferred()

    def cb(sdref, flags, interface_index, error_code, service_full_name,
           fqdn, port, txt_record):
        # stop reading the bonjour dns record because the result has been
        # obtained
        reader.stopReading()

        # if there is an error, errback it and exit function
        if error_code != pybonjour.kDNSServiceErr_NoError:
            d.errback(pybonjour.BonjourError(error_code))
            return

        # return a tuple with the new details for the service
        d.callback((service_full_name, fqdn, port, txt_record,))

    sdref = pybonjour.DNSServiceResolve(0,
                                        interface_index,
                                        service_name,
                                        registry_type,
                                        reply_domain,
                                        cb
                                        )
    if protocol is None:
        protocol = DiscoverProtocol()

    reader = BonjourReader(protocol, sdref)
    reader.startReading()
    return d


def connectBonjour(*args, **kwargs):
    """ 
    Creates a broadcast service via broadcast.
    
    @note: this is a shortcut if you are not using twisted.application.service.
            See tap.py.
    @see: txbonjour.tap
    @param args: All the same args as broadcast 
    @return: a BonjourService instance.
    @rtype: txbonjour.service.BonjourService
    
    @see: http://twistedmatrix.com/documents/12.2.0/core/howto/application.html 
    """
    reader = broadcast(*args, _do_start=False, **kwargs)
    return BonjourService(reader)


def listenBonjour(*args, **kwargs):
    """ 
    Creates a discover service via discover.
    
    @note: this is a shortcut if you are not using twisted.application.service.
            See tap.py.
    @see: txbonjour.tap
    @return: a BonjourService instance.
    @rtype: txbonjour.service.BonjourService
    
    @see: http://twistedmatrix.com/documents/12.2.0/core/howto/application.html 
    """
    reader = discover(*args, _do_start=False, **kwargs)
    return BonjourService(reader)


# backwards compat
make_broadcast_service = connectBonjour
make_discover_service = listenBonjour
