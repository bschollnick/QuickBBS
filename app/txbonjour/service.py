'''
Created on 2013-02-09

@author: jdcumpson
@author: Noobie
@copyright: (c) JD Cumpson 2013.
'''
import pybonjour
from zope import interface
from twisted.internet import interfaces, abstract
from twisted.internet.main import CONNECTION_DONE
from twisted.internet import protocol, abstract
from twisted.application.internet import _VolatileDataService
from twisted.python import log, failure

class IBonjourProtocol(interface.Interface):
    def connectionMade(self):
        """
        We have made a connection to the bonjour service.
        """
        
    def connectionLost(self, reason):
        """
        The connection was lost for some reason.
        """

class IBroadcastProtocol(IBonjourProtocol):
    """
    A protocol to use with broadcasting services.
    """
    def registerReceived(self):
        """
        We have been registered and are now broadcasting
        """

class IDiscoverProtocol(IBonjourProtocol):
    """
    A protocol to use with browsing services.
    """
    
    def browseError(self, *args):
        """
        There was an error while browsing a service.
        """
        
    def resolveError(self, *args):
        """
        There was an error resolving a service.
        """
    
    def addService(self, *args):
        """
        Adding a service to our services list.
        """
        
    def removeService(self, *args):
        """
        Removing a service to our services list.
        """
        

class BonjourReader(abstract.FileDescriptor):
    """ 
    A service reader is a FileDescriptor-like object that is specific to reading
    services that use FD to output their data. The service descriptor will
    take a service descriptor reference and wrap it in a twisted friendly
    interface that our reactor can read and use.
        
    @see: http://wikipedia.org/wiki/File_descriptor
    @see: http://http://twistedmatrix.com/documents/
                current/api/twisted.internet.interfaces.IReactorFDSet.html
    """
    
    _logstr = None
    
    def __init__(self, protocol, sdref, reactor=None):
        """
        @param sdref: a service descriptor reference
        """
        if not reactor:
            from twisted.internet import reactor
            self.reactor = reactor
            
        self.sdref = sdref
        self.protocol = protocol
        self.protocol.reader = self
        self.setLogStr()
        
    def doRead(self):
        """ 
        Doesn't return data like normal FD's because it processes the
        information and calls any registered callbacks.
        """
        # XXX: there is no guarantee that this isn't blocking but I hope it is
        #        Otherwise, need to make a process runner instead.
        pybonjour.DNSServiceProcessResult(self.sdref)
        
    def startReading(self):
        self.reactor.addReader(self)
        self.connected = 1
        self.protocol.connectionMade()
        
    def stopReading(self):
        self.reactor.removeReader(self)
        self.connected = 0
        
    def fileno(self):
        try:
            return self.sdref.fileno()
        except Exception:
            return None
        
    def connectionLost(self, reason=None):
        try:
            self.sdref.close()
        except Exception as e:
#            log.err(e, 'Unable to close %s' % (self))
            pass
        self.protocol.connectionLost(reason)
        
    def loseConnection(self):
        """ 
        Close the service connection at the next available opportunity.
        """
        if self.connected and not self.disconnecting:
            self.disconnecting = 1
            self.stopReading()
            self.connectionLost(failure.Failure(CONNECTION_DONE))
            
    def setLogStr(self):
        logPrefix = self._getLogPrefix(self.protocol)
        self._logstr = '%s (Bonjour)' % logPrefix

    def logPrefix(self):
        return self._logstr


class BonjourService(_VolatileDataService):
    """ 
    A very simplistic Twisted service implementation so that you can run
    txbonjour as a service too.
    
    @see: http://twistedmatrix.com/documents/12.2.0/core/howto/application.html
    @
    """
    
    def __init__(self, reader):
        self.reader = reader
        
    def startService(self):
        _VolatileDataService.startService(self)
        self.reader.startReading()
        
    def stopService(self):
        _VolatileDataService.stopService(self)
        try:
            self.reader.loseConnection()
        except:
            pass
        self.reader = None
