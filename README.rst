================================================
 ``refresher``: Yet another HTML live-previewer
================================================

``refresher`` is yet another program for serving and
HTML/CSS/JavaScript/etc. files in a directory and reloading them upon
updates.  It is based on excellent libraries such as Trio_, Quart_,
Watchdog_, and `LiveReload.js`_.

Features:

* Serving files temporary vanished from the file system by caching
  them in memory.  This is useful when creating web pages with build
  process that takes time to complete.  Use Ctrl-Shift-R to completely
  refresh the web page.
* Auto-generate deterministic port number from (the hash of) the root
  path of the web page. Each project gets virtually unique and static
  port number.

.. _Trio: https://trio.readthedocs.io
.. _Quart: https://pgjones.gitlab.io/quart/
.. _Watchdog: https://python-watchdog.readthedocs.io
.. _LiveReload.js: https://github.com/livereload/livereload-js
