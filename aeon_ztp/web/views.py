#!/usr/bin/env python
# Copyright 2014-present, Apstra, Inc. All rights reserved.
#
# This source code is licensed under End User License Agreement found in the
# LICENSE file at http://www.apstra.com/community/eula
#
# Web Handlers to make it easier to manage Aeon-ZTP via a web interface.
#
# TODO: Find a better way of checking for the appropriate syslog filename or an API dedicated to find it
# (eg /var/log/messages /var/log/syslog)
import errno
import os
import pwd
import re
import datetime
import shutil
import subprocess
from distutils.dir_util import copy_tree

import aeon_ztp
import magic
from flask import Blueprint, send_from_directory, render_template, url_for, g, request, flash, redirect
from flask import current_app as app
# from flaskext.markdown import Markdown
from isc_dhcp_leases.iscdhcpleases import IscDhcpLeases
from pygments import highlight
from pygments.formatters import HtmlFormatter
from pygments.lexers import get_lexer_for_filename
from pygments.lexers.special import TextLexer
from pygments.util import ClassNotFound
from werkzeug.utils import secure_filename

from aeon_ztp import ztp_os_selector
from aeon_ztp.api import models
from ztp_sudo import flush_dhcp

_syslog_file = "/var/log/syslog"
_dhcp_leases_file = '/var/lib/dhcp/dhcpd.leases'

_AEON_TOPDIR = os.getenv('AEON_TOPDIR')
# TODO _AEON_SYSLOG = os.getenv('AEON_SYSLOG')
# TODO _AEON_DHCP = os.getenv('AEON_DHCP')

web = Blueprint('web', __name__, template_folder='templates', static_url_path='/web/static', static_folder='static')

# Commenting this out. When this web/views.py is imported by create_app, this command is trying to
# use the app object before it's fully initialized.
# TODO: Figure out how to make this work. Maybe it just needs to be in a function so that it's not run when this module is imported.
# Markdown(app)


@web.context_processor
def valid_logs():
    """ List of valid log files to query within Aeon-ZTP

    Returns:
        dict: A dictionary of valid logs.  For example:

    """
    logs = {
        'dhcp': {
            'filename': _syslog_file,
            'search': 'dhcp',
            'description': 'Syslog file filtered for dhcp'
        },
        'tftp': {
            'filename': _syslog_file,
            'search': 'tftp',
            'description': 'Syslog file filtered for tftp'
        },
        'uwsgi': {
            'filename': '/var/log/uwsgi/app/aeon-ztp.log',
            'search': '',
            'description': 'Aeon UWSGI Web application logs (not very useful)'
        },
        'bootstrapper': {
            'filename': '/var/log/aeon-ztp/bootstrapper.log',
            'search': '',
            'description': 'Aeon ZTP Bootstrapper log files'
        },
        'nginx-access': {
            'filename': '/var/log/aeon-ztp/nginx.access.log',
            'search': '',
            'description': 'Nginx access logs'
        },
        'nginx-error': {
            'filename': '/var/log/aeon-ztp/nginx.error.log',
            'search': '',
            'description': 'Nginx error logs'
        },
        'celery': {
            'filename': '/var/log/aeon-ztp/worker1.log',
            'search': '',
            'description': 'Celery worker logs'
        }
    }
    return logs


def scrape_file(filename, search, searchfilter='', lineno=0):
    """ Scrapes target filename for searching line entries from 'search' variable
    Args:
        search string: String to look for
        filter string: refine results
        filename string: filename to look through

    Returns:
        return list: List of searching syslog entries

    Examples:
        >>> for i in scrape_file(filename='/var/log/syslog', filter='tftp', searchfilter='':
                print i
            'Aug 19 17:05:25 aeon-ztps tftpd[5619]: tftpd: serving file from /opt/aeonztps/tftpboot'

    """
    lines = []
    try:
        with open(filename, "r") as f:
            for line in f:
                # A bit lazy: could maybe be faster.
                if search in line.lower() and searchfilter in line.lower():
                    lines.append(line.replace('\n', ''))
            if lineno:
                return lines
            return lines
    except IOError as e:
        code = e.args[0]
        reason = e.args[1]

    # Permissions issue. Cannot read syslog
    if code == errno.EACCES:
        whoami = pwd.getpwuid(os.getuid())[0]
        lines.append("Error: Permission denied: add {whoami} user read access to {filename}".format(filename=filename,
                                                                                                    whoami=whoami))

        # All other errors
    lines.append(
        "Could not read syslog for {search}: {reason} ({code}) reading {filename}".format(search=search, code=code,
                                                                                          reason=reason,
                                                                                          filename=filename))
    return lines


def show_dir(directory):
    """ Lists files in directory
    param directory string: Directory to list files for
    """
    file_retr = []
    for root, _, files in os.walk(os.path.join(_AEON_TOPDIR, directory)):
        for f in files:
            # Don't show hidden files
            if f[0] != '.':
                fullpath = os.path.join(root, f)
                # path without topdir
                file_retr.append(fullpath.split(_AEON_TOPDIR).pop())
    return file_retr


def valid_ip(string):
    """ Checks if given string is a valid IP address

    Args:
        string (str): String to check IP against

    Returns:
        bool: True if string is a dotted-quad IP address
    """
    if re.search(r"^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$", string):
        return True
    return False


def allowed_file(folder, filename):
    """ Checks if a folder, filename is permitted read or write access within this application

    Args:
        folder (str): Root folder to check file path for
        filename (str): Specific file to check access for

    Returns:
        bool: True if access to this file is permitted by the result

    """
    if allowed_path(folder):
        return True
    return False


def allowed_path(folder):
    """ Checks against valid_paths if specified folder is permitted within the application

    Args:
        folder (str): Folder name to search for

    Returns:
        bool: True if path exists in application

    """
    # TODO: Absolute path checking
    folder = folder.strip('/')
    for path in valid_paths():
        if folder.startswith(path.strip('/')):
            return True
    return False


def valid_paths():
    """ A list of valid path names permitted within this application context

    Returns:
        list: List of valid root paths

    """
    return [
        '/downloads',
        '/etc',
        '/vendor_images',
        '/tftpboot',
        '/bin'
    ]


def git_commit(message):
    olddir = os.getcwd()
    os.chdir(_AEON_TOPDIR)
    try:
        subprocess.check_output(['git', 'add', 'etc'])
        subprocess.check_output(["git diff-index --quiet HEAD || git commit -m '%s'" % (message) ], shell=True)
    except:
        raise

    os.chdir(olddir)
    return


# FLASK ROUTING

@web.before_request
def _global_variables():
    """ Global variable loading for flask template rendering
    """
    # Used by base.html to add meta refresh to pages
    timer = request.args.get('refresh')
    if timer > 0:
        g.refresh = timer
    g.valid_logs = valid_logs()
    g.valid_paths = valid_paths()
    g.alert = dict(status=None, reason=None)


@web.route('/')
def index():
    """ Index page of web application
    """
    data = {}
    data["cfggitpresent"] = False

    if os.path.isdir(os.path.join(_AEON_TOPDIR, ".git")):
        data["cfggitpresent"] = True

    return render_template('index.html', data = data)

@web.route('/nos_readme')
def nos_readme():
    return render_template('nos_readme.html')

@web.route('/vendor_images/<path:image>')
def download_vendor_image(image):
    """ Downloads specified vendor binary image

    Args:
        image (str): Path of image filename to begin downloading

    Returns:

    """
    # TODO Prevent sending hidden files
    return send_from_directory(os.path.join(_AEON_TOPDIR, 'vendor_images'), image)


@web.route('/etc/<path:image>')
def etc_image(image):
    """ Serves a file from the etc folder
    Args:
        image (str): Filename of image
    """
    # TODO Prevent sending hidden files
    return send_from_directory(os.path.join(_AEON_TOPDIR, 'etc'), image)


@web.route('/logs', defaults={'log': None})
@web.route('/logs/<log>')
def show_log(log):
    """ Renders display of specified log file - if no log is specified, displays selection list of available logs.

    Args:
        log (str): Name of log file

    Returns:
        Rendered results of show_log.html
    """

    def get_log(getlog):
        """ Small internal function to get a log file contents based on log name

        Args:
            getlog (str): Name of logfile to obtain

        Returns:
            list: List of \n-separated log lines from specified log file

        """
        filename = valid_logs()[getlog]['filename']
        search = valid_logs()[getlog]['search']
        return scrape_file(filename=filename, search=search, searchfilter=searchfilter, lineno=lineno)

    lines = []
    searchfilter = request.args.get('searchfilter')
    if not searchfilter:
        searchfilter = ''
    lineno = request.args.get('lineno')
    if not lineno:
        lineno = ''
    if valid_ip(searchfilter):
        g.ip = searchfilter
    checkbox = []
    # List of logs from checkbox?
    if log in valid_logs() and log is not None:
        lines = get_log(log)
    else:
        for i in valid_logs():
            if request.args.get(i) or log == 'all':
                lines = lines + get_log(i)
                checkbox.append(i)
    return render_template('show_log.html', lines=lines, log=log, checkbox=checkbox)


@web.route('/sitemap')
def site_map():
    """ Renders a simple site map from links.html

    """
    g.title = "Site Map"
    links = []
    # TODO - Sorted
    for rule in app.url_map.iter_rules():
        links.append(rule)
    return render_template('links.html', links=links)


@web.route('/status')
def status():
    """ Renders a simple device status webpage for all ZTP-DB devices
    """
    db = aeon_ztp.db.session
    devices = db.query(models.Device)
    g.title = "Device Status"
    return render_template('status.html', devices=devices)


@web.route('/status/ip/<ip>')
def status_for_ip(ip):
    """ Returns a status page for specific IP address. (eg nxos, cumulus, eos)

    Args:
        ip (str): dotted-quad IP address to check ZTP database for.

    """
    db = aeon_ztp.db.session
    g.ip = ip
    devices = db.query(models.Device).filter(models.Device.ip_addr == ip)
    g.title = "Device Status"
    return render_template('status.html', devices=devices)


@web.route('/status/os/<osname>')
def status_for_os(osname):
    """ Returns status page for specified OS list (eg nxos, cumulus, eos)

    Args:
        osname (str): OS Vendor shortname to search for


    """
    db = aeon_ztp.db.session
    devices = db.query(models.Device).filter(models.Device.os_name == osname)
    g.title = "Device Status"
    return render_template('status.html', devices=devices)

@web.route('/cfgbrowse')
def cfgbrowse():
    base = request.headers.get('Host').split(':')[0]
    return redirect("http://%s:9000/ztpcfg" % (base), code=302)

@web.route('/cfg')
def cfg():
    data = {}
    data["cfggitpresent"] = False

    if os.path.isdir(os.path.join(_AEON_TOPDIR, ".git")):
        data["cfggitpresent"] = True
    return render_template('cfg.html', data = data)

@web.route('/status/hw/<hw>')
def status_for_hw(hw):
    """ Status page for specific hardware type

    Args:
        hw (str): Hardware type to filter by

    """
    db = aeon_ztp.db.session
    devices = db.query(models.Device).filter(models.Device.hw_model == hw)
    g.title = "Device Status"
    return render_template('status.html', devices=devices)


@web.route('/dhcp/flush')
def dhcp_flush():
    """ Flushes the current DHCP leases from the system """
    try:
        flush_dhcp()
        flash('Successfully Flushed DHCP leases', 'success')
        return redirect(url_for('dhcp_leases'), code=302)
    except OSError as e:
        flash('Could not flush DHCP {}'.format(e), 'danger')
        return redirect(url_for('dhcp_leases'), code=302)


@web.route('/dhcp')
def dhcp_leases():
    """ Shows a webpage containing DHCP leases.  Uses isc_dhcp_leases package to parse text filel.

    """
    try:
        leases = IscDhcpLeases(_dhcp_leases_file)
        dhcp = leases.get()
        ip = request.args.get('ip')
        g.ip = ip
        # Only return results for one IP if filtering
        if ip and valid_ip(ip):
            for lease in dhcp:
                if lease.ip == ip:
                    return render_template('dhcp.html', dhcp=[lease])
            # No matching leases
            return render_template('dhcp.html')
        return render_template('dhcp.html', dhcp=dhcp)
    except IOError as e:
        code = e.args[0]
        reason = e.args[1]

    # Permissions issue. Cannot read DHCP
    if code == errno.EACCES:
        whoami = pwd.getpwuid(os.getuid())[0]
        error = "Could not read DHCP Leases file - permission denied. Add {whoami} " \
                "read access: {reason} ({code}) reading {filename}".format(
                    code=code, reason=reason, filename=_dhcp_leases_file, whoami=whoami)
        flash(error, 'danger')
        return render_template('dhcp.html')

    # All other errors
    error = "Could not read DHCP Leases file: {reason} ({code}) reading {filename}".format(code=code, reason=reason,
                                                                                           filename=_dhcp_leases_file)
    flash(error, 'danger')
    return render_template('error.html', error=error)


@web.route('/cfginit', methods=['POST'])
def cfginit():
    remoteip = request.remote_addr
    basegitignore = """
*
!*/
!etc/**
"""
    importform = None
    try:
        importform = request.form.get('import')
    except:
        pass

    my_env = dict(os.environ, GIT_TERMINAL_PROMPT='0', GIT_SSH_COMMAND='ssh -oBatchMode=yes')
    currentdir = os.getcwd()
    os.chdir(_AEON_TOPDIR)
    try:
        if importform:
            subprocess.check_output(['git', 'clone', '--bare',  importform, '.git'], env=my_env)
            subprocess.check_output(['git', 'init'])
            subprocess.check_output(['git', 'reset', '--hard'])
        else:
            f = open(".gitignore", "w")
            f.write(basegitignore)
            f.close()
            subprocess.check_output(['git', 'init'])
            subprocess.check_output(['git', 'config', 'user.name', 'ztp'])
            subprocess.check_output(['git', 'config', 'user.email', 'ztpserver@ztpserver'])
            subprocess.check_output(['git', 'add', 'etc'])
            subprocess.check_output(['git', 'commit', '-m Initialize ZTP config repo (triggerd from %s)' % (remoteip) ])
            #
    except Exception as e:
        flash(e.message, 'danger')
        return render_template('error.html', error=e.message)

    os.chdir(currentdir)
    return index()


@web.route('/copydir/<path:folder>', methods=['POST'])
def copydir(folder):
    if not allowed_path(folder):
        return render_template('error.html', error="Invalid path to upload to {}".format(folder))

    src = ""
    dest = ""
    srcpath = ""
    dstpath = ""

    try:
        dest =  secure_filename(request.form.get("dest"))
        dstpath = os.path.join(_AEON_TOPDIR, folder, dest)
    except:
        flash('Target directory must be provided', 'danger');


    try:
        src = secure_filename(request.form.get("src"))
        srcpath = os.path.join(_AEON_TOPDIR, folder, src)
    except:
        pass

    if os.path.isdir(dstpath):
        flash('Target directory {dest} already exists'.format(dest=dest), "danger")
        return browse(root=folder)

    if src != None and not os.path.isdir(srcpath):
        flash('Target directory {src} does not exist'.format(src=src), "danger")
        return browse(root=folder)

    try:
        if src:
            copy_tree(srcpath, dstpath)
            git_commit("Created directory {dest} from {src} (triggered by web from {remote})".format(dest=dest, src=src, remote=request.remote_addr))
            flash('Created directory {dest} from {src}'.format(dest=dest, src=src), 'success')
        else:
            os.makedirs(dstpath)
            git_commit("Created directory {dest} (triggered by web from {remote})".format(dest=dest, src=src, remote=request.remote_addr))
            flash('Created directory {dest}'.format(dest=dest), 'success')
    except Exception as e:
        flash(e.message, 'danger')
        return browse(root=folder)


    return browse(root=folder)



@web.route('/upload/<path:folder>', methods=['POST'])
def upload(folder):
    """ For uploading files and folders to specified paths.

    Args:
        folder (str): Folder path to upload file to.  Only can be learned from valid_paths() and allowed_folder().

    """
    if not allowed_path(folder):
        return render_template('error.html', error="Invalid path to upload to {}".format(folder))
    if 'file' not in request.files:
        return render_template('error.html', error="No file upload")
    filename = request.files['file']

    s_filename = secure_filename(filename.filename)

    if filename.filename == '':
        return render_template('error.html', error="No selected file")
    if not allowed_file(folder, filename.filename):
        return render_template('error.html', error="File not permitted")

    # check if we have access before just doing this
    filepath = os.path.join(_AEON_TOPDIR, folder, filename.filename)

    if filename:
        try:
            filename.save(filepath)
            git_commit("Add {folder}/{file} (triggered by web from {remote})".format(folder=folder,file=filename.filename, remote=request.remote_addr))
            # upload success!
            flash('File upload successful:{file}'.format(file=filepath), 'success')
            return browse(root=folder)

        except (IOError, OSError) as e:
            code = e.args[0]
            reason = e.args[1]
            if code == errno.EACCES:
                whoami = pwd.getpwuid(os.getuid())[0]
                error = "Could not write {filename} to {filepath} - for {whoami}: {reason} ({code})".format(
                    whoami=whoami, filepath=filepath, filename=s_filename, code=code, reason=reason)
                flash(error, 'danger')
        return browse(root=folder)
    else:
        error = "Could not write file {filename} to {filepath}".format(filename=s_filename, filepath=filepath)
        flash(error, 'warning')
        return browse(root=folder)


@web.route('/browse', defaults={'root': '/'})
@web.route('/browse/', defaults={'root': '/'})
@web.route('/browse/<path:root>')
def browse(root):
    """ Lists root, files, and file names in root folder

    Args:
        directory (str): Directory to list files for

    """
    path = os.path.join(_AEON_TOPDIR, root)

    if not os.access(path, os.R_OK):
        flash('Access Denied reading {path}'.format(path=path), 'warning')
        root = '/'

    if root == '/':
        dirnames = []
        for path in valid_paths():
            dirnames.append(path.strip('/'))
        parent = '/'
        filenames = []
        dirpath = '/'
        return render_template('browse.html', dirpath=dirpath, dirnames=dirnames, filenames=filenames, parent=parent)

    folder = os.walk(path).next()
    parent = os.path.join(path, os.pardir).split(_AEON_TOPDIR).pop().strip('/')
    dirpath = folder[0].split(_AEON_TOPDIR).pop().strip('/')
    dirnames = [x.split(_AEON_TOPDIR).pop() for x in folder[1]]
    mime = magic.Magic(mime=True)

    dirnames.sort()

    files = []
    for filename in folder[2]:
        f = os.path.join(_AEON_TOPDIR, root, filename)
        # If it's a symlink we want to follow it for accurate stats
        # if os.path.islink(f):
        #     # works for absolute paths
        #     # TODO: fix for relative symlink
        #     f = os.readlink(f)

        stat = os.stat(f)
        mimetype = mime.from_file(f)
        # icon = get_icon(mimetype)
        size = stat.st_size
        # mtime = stat.st_mtime
        mtime = datetime.datetime.fromtimestamp(stat.st_mtime).strftime("%d-%m-%Y %H:%M:%S")
        ctime = datetime.datetime.fromtimestamp(stat.st_ctime).strftime("%d-%m-%Y %H:%M:%S")
        name = filename
        files.append({'name': name, 'size': size, 'mtime': mtime, 'ctime': ctime, 'mimetype': mimetype, 'link': f})

    return render_template('browse.html', dirpath=dirpath, dirnames=dirnames, files=files, parent=parent)


# TODO: constraint to POST or DELETE
@web.route('/devices/delete/<ip>')
def delete_device(ip):
    """ Deletes a specific IP address device from ZTP database.

    Args:
        ip (str): IP address to delete from the ZTP Database.

    """
    db = aeon_ztp.db.session
    g.ip = ip
    deldevices = db.query(models.Device).filter(models.Device.ip_addr == ip)
    count = deldevices.count()
    deldevices.delete(synchronize_session=False)
    db.commit()
    flash('Deleted {} entries from ZTP DB'.format(count), 'success')
    return redirect(url_for('web.status'))


@web.route('/view/<path:filename>')
def view_file(filename):
    """ Views file with syntax highlighting (if applicable)

    Args:
        filename (str): Full path to filename to render view response for.
    """
    folder = filename.split(_AEON_TOPDIR).pop().strip('/')
    filename = os.path.join(_AEON_TOPDIR, filename)
    try:
        with open(filename, 'r') as f:
            data = f.read()

            # lexer = guess_lexer_for_filename(filename, data)
            formatter = HtmlFormatter(linenos=True)
        try:
            lexer = get_lexer_for_filename(filename)
            code = highlight(data, lexer, formatter)
        except ClassNotFound:
            lexer = TextLexer()
            code = highlight(data, lexer, formatter)
        stat = os.stat(filename)
        return render_template('view.html', content=code, folder=folder, stat=stat, filename=os.path.basename(filename))

    except (OSError, IOError) as e:
        code = e[0]
        reason = e[1]
        flash('Error: Could not view file {filename}: {reason} ({code})'.format(filename=filename, reason=reason,
                                                                                code=code), 'danger')
        return render_template('view.html')


@web.route('/delete/<path:filename>')
def delete_file(filename):
    """ Deletes specified file from the filesystem based on path
        Only specific paths/filenames can be deleted as per allowed_folder and allowed_path functions.

    Args:
        filename (str):

    Returns:

    """
    inputf = filename
    folder = os.path.split(filename)[0]
    filename = os.path.join(_AEON_TOPDIR, filename)

    if (os.path.isdir(filename)):
        try:
            shutil.rmtree(filename)
            git_commit("Deleted {file} (triggered by web from {remote})".format(file=inputf, remote=request.remote_addr))
            flash('Deleted directory: {filename}'.format(filename=filename), 'success')
            return browse(root=folder)

        except (IOError, OSError) as e:
            code = e[0]
            reason = e[1]
            flash('Error: Could not delete directory {filename}: {reason} ({code})'.format(filename=filename, reason=reason,
                                                                                  code=code), 'danger')
            return browse(root=folder)

    else:
        # TODO: check if path is allowed first
        try:
            os.remove(filename)
            git_commit("Deleted {file} (triggered by web from {remote})".format(file=inputf, remote=request.remote_addr))
            flash('Deleted file: {filename}'.format(filename=filename), 'success')
            return browse(root=folder)

        except (IOError, OSError) as e:
            code = e[0]
            reason = e[1]
            flash('Error: Could not delete file {filename}: {reason} ({code})'.format(filename=filename, reason=reason,
                                                                                      code=code), 'danger')
            return browse(root=folder)


@web.route('/firmware')
def firmware():
    """ Displays a simple status page describing if vendor file images are on the disk or not, and what their versions
        are expected to be.

    """
    os_list = []
    for vendor in ztp_os_selector.vendor_list():
        os_list.append(ztp_os_selector.Vendor(vendor))
    return render_template('firmware.html', list=os_list)
