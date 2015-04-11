#
# This code is public domain, No license, completely unrestricted and without warranty
# russell.ballestrini.net
#

class Bread( object ):
    """
    Create Bread object
    ----------------------------------------
    >>> from bread import Bread
    >>> bread = Bread( "http://www.foxhop.net/samsung/HL-T5087SA/red-LED-failure" )
    >>> print bread.crumbs
    >>> print bread.links
    
    """
    def __init__( self, uri=None ):
        if uri: self.uri = uri # invoke uri.setter
        else: self._uri = uri  # set _uri to none
        
        self.include_protocol = True
        
    @property
    def uri( self ):
        return self._uri

    @uri.setter
    def uri( self, uri ):
        """set the _uri, _protocol, and crumbs attributes"""
        self._protocol = 'http://'
        protocols = ['http://', 'https://', 'ftp://', 'sftp://']
        for protocol in protocols:
            if uri.startswith( protocol ): 
                self._protocol = protocol
                uri = uri[ len(protocol): ] # remove protocol from uri

        self._uri = uri.rstrip('/')
        self.crumbs = self._uri.split('/')
        
    @property
    def links( self ):
        links = []
        for count, crumb in enumerate( self.crumbs, start = 1 ):
            if self.include_protocol:
                crumb_uri = self._protocol
            else:
                crumb_uri = ""
            
            crumb_uri += '/'.join( self.crumbs[ 0:count ] )
            links.append( '<a href="' + crumb_uri + '" class="breadcrumbs">' + crumb + '</a>' )
#            links.append( (crumb, '<a href="' + crumb_uri + '" class="breadcrumbs">' + crumb + '</a>' ) )
        return links
        
if __name__ == "__main__":
    print '\n'
    bread = Bread( "http://www.foxhop.net/samsung/HL-T5087SA/red-LED-failure" )
    print bread.uri
    print bread.crumbs
    print bread.links
    print '\n'
    bread.uri = 'https://encrypted.google.com/search?q=foxhop'
    print bread.uri
    print bread.crumbs
    print bread.links
    print '\n'
    bread = Bread()
    bread.uri = 'russell.ballestrini.net'
    print bread.uri
    print bread.crumbs
    print bread.links
    print '\n'
    bread = Bread('ftp://ftp.computalynx.net/pub/Alpha')
    print bread.uri
    print bread.crumbs
    print bread.links

