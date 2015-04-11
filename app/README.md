User-authentication for a Twisted web-site
================================================

I like using Twisted for building little web-sites that consist of a
single-page app, some static resources, and an Autobahn web-sockets
server.  Most of the single-page applications I've written require
authentication against a database of users.  For these apps, it is
best if authentication is handled by a separate login page that guards
the single-page app.  Twisted web-server does not ship with a HTML
Form-based user authentication, but it isn't too hard to write the
logic.  That's what we'll show here.

This repository contains a tiny application that demonstrates a
pattern for user-authentication.  It combines the following elements.

- [Twisted](https://twistedmatrix.com) web server
- Form-based User authentication against a SQLite3 database
- [Jinja2](http://jinja.pocoo.org/) for templating
- [Twitter Bootstrap](http://getbootstrap.com/) for styling
- simple CSRF token (a la [CSurf](https://github.com/expressjs/csurf))

The code is based on patterns embodied by Rails and Express, but is
re-cast here using Python and Twisted ... and in greatly simplified
form.  Whereas Rails has an extensive system of before-filters that
can intercept requests and interpose re-directs,  in our example
we must write out

```python
user = current_user(request)

if not user:
    # this should store the current path, render the login page, and finally redirect back here
    return require_login(request)
```

to get the same effect.  Read on if interested.  I hope that some of
this can be useful to someone.

## Try it out

Make sure you have installed Twisted and Jinja2.  Then run the
following.

```sh
python -m muet.login_logic_jinja2 &
```

You should be able to login with any of the username/password
combinations below.

- user1/pass1
- user2/pass2
- user3/pass3
- user4/pass4

Go to the home page: [http://localhost:8880](http://localhost:8880).  You should be able to
cleanly login and logout of the application, and the name of the
current user should appear in the top-right of the main page.

![Main Page](images/muet_page.png)

## Session Storage
    
Twisted provides a nice in-memory session storage mechanism.  Calling
the `getSession` method on a request will retrieve the session of the
current request, or create a new session if necessary.

```python
    session = request.getSession()
```

To add specific named attributes to the session, a component adapter
must be defined.  In our example, we define an interface called
`ILoginSessionData`.  It defines three attributes, each of which are strings.

- username: the current user
- csrf: a cross-site request-forgery token
- urlref: a redirect of where to go to after authentication

With this definition, our example can access session storage to
determine the current user, or to set it.

```python
   session = request.getSession()
   login = ILoginSessionData(session)
   username = login.username
   print "CURRENT_USER:%s" % username
```

## Template Mechanism

Jinja2 is a popular templating engine for use in Python programs.  In
our example, the main package is called `muet` and a sub-directory of
this package holds the page templates.  Jinja2 is configured to find
its templates in this directory by defining an environment.

```python
    from jinja2 import Template, Environment, PackageLoader
    env = Environment(loader=PackageLoader('muet', 'templates')) # templates dir under muet package
```

Then, as pages are needed by resources for rendering, they can be
rendered into strings this way.  The context variable (`ctx`) is a
dictionary of strings to be interpolated into the templates.

```python
    template = env.get_template("page_name.html")
    ctx = { ... dictionary of variables ... }
    return str(template.render(ctx))
```
    

## Login/Logout Logic

The logic of the application is fairly simple.  The application
consists of three pages, mounted at the following points.

- /login
- /logout
- /index

The Root of the application ("/") always attempts to re-direct the
browser to the Index page.  The `render_GET` method of the Index page
is guarded with the following pattern.

```python
def render_GET(self, request):
    user = current_user(request)

    if not user:
        # this should store the current path, render the login page, and finally redirect back here
        return require_login(request)

    ...
    ...
    return str(template.render(ctx))
```

This code looks up the current user.  If there is no user, then it
calls `require_login`.  The `require_login` function stores the
current path in the `urlref` attribute of the session and then
redirects to the login page.  Any number of resources can be guarded
with this same pattern in the `render_GET` method.

The LoginPage Resource contains the tricky logic.  The `render_GET`
method generates a CSRF token and then renders the `login_greeting`
page from the templates directory.

Upon completing filling-out the Login form, a user's browser POSTs the
form contents back to the LoginPage Resource.  The `render_POST`
method retrieves the FORM POST data.  It first verifies the CSRF
token, and then performs a database lookup to see if the password
given matches the password expected.  (Note: a better implementation
would salt the password ...)  If password checking succeeds, then the
user is granted access to the `urlref` page.  If not, the user is sent back
to the Login page.  Etcetera.

The LogoutPage performs one essential function: it clears the current
session.

```python
class LogoutPage(Resource):

    def render_GET(self, request):
        request.getSession().expire()

        ctx = {
            }
        template = env.get_template("logout_greeting.html")

        return str(template.render(ctx))
```


## Define your own database

See the note in `db/notes.txt` for a sketch of populating the sqlite3 database.


## See Also

[Adding User-Authentcation to your Twisted web-site](http://blog.vrplumber.com/b/2004/09/27/adding-user-authentication-to/)
