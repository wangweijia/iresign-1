#!/usr/bin/env python
# coding: utf-8
"""
    iResign
    ~~~~~~~

    iResign is a tool for recodesigning iOS applications.  There are many
    scripts with similar functionality but iResign is my very own bicycle.

    The script written just for fun. I just want to print some useful info
    during recodesigning and this script does it well! Moreover, it's Python
    so you can easy to extend it in your own way.

    :copyright: (c) 2013, Igor Kalnitsky <igor@kalnitsky.org>
    :license: BSD, see LICENSE for details.
"""
import os
import sys
import shutil
import argparse
import plistlib
import tempfile
import subprocess
import zipfile


__version__ = '0.2.2'


PY2 = sys.version_info[0] == 2
if PY2:
    write_plist_to_string = plistlib.writePlistToString

    def read_plist_from_string(data):
        """
        Parse a given data and return a plist object. If a given data has a
        binary signature it will be striped before parsing.
        """
        # strip binary signature if exists
        beg, end = '<?xml', '</plist>'
        beg, end = data.index(beg), data.index(end) + len(end)
        data = data[beg: end]

        return plistlib.readPlistFromString(data)
else:
    write_plist_to_string = plistlib.writePlistToBytes

    def read_plist_from_string(data):
        """
        Parse a given data and return a plist object. If a given data has a
        binary signature it will be striped before parsing.
        """
        data = data.decode('latin1')

        # strip binary signature if exists
        beg, end = '<?xml', '</plist>'
        beg, end = data.index(beg), data.index(end) + len(end)
        data = data[beg: end]

        data = data.encode('latin1')
        return plistlib.readPlistFromBytes(data)


def read_provisioning_profile(filename):
    """
    Read and parse a given filename as provisioning profile, and return
    a `dict` with profile's attributes.
    """

    content = {}
    with open(filename, 'rb') as f:
        content = read_plist_from_string(f.read())

    return {
        'filename':      filename,
        'uuid':          content['UUID'],
        'name':          content['Name'],
        'app_id_prefix': content['ApplicationIdentifierPrefix'][0],
        'entitlements':  content['Entitlements'],
        'app_id':        content['Entitlements']['application-identifier'],
        'aps_env':       content['Entitlements'].get('aps-environment', None),
        'task_allow':    content['Entitlements']['get-task-allow'],
    }


def read_application(filename):
    """
    Read iOS application file (.app) and return a `dict` with application's
    attributes.
    """
    provision = os.path.join(filename, 'embedded.mobileprovision')
    return {
        'filename':   os.path.abspath(filename),
        'provision':  read_provisioning_profile(provision),
    }


def generate_entitlements(provision_entitlements, app):
    """
    Merge provision entitlements with application one. We really need
    to save a `keychain-access-groups` from the embedded entitlements.
    """
    # get keychain-access-groups from the application
    command = 'codesign --display --entitlements - "{app}" 2> /dev/null'
    p = subprocess.Popen(command.format(
        app=app['filename']
    ), shell=True, stdout=subprocess.PIPE)

    print "-=-=-=-=-=-=-=-run command-=-=-=-=-=-=-=-"
    print command.format(
        app=app['filename']
    )
    if p.stderr:
        print "-=-=-=-=-=-=-=-command error or Warning-=-=-=-=-=-=-=-"
        print p.stderr.read()
        pass

    entitlements = read_plist_from_string(p.communicate()[0])
    access_groups = entitlements.get('keychain-access-groups')

    # use application keychain-acccess-groups in the new entitlements
    if access_groups:
        provision_entitlements['keychain-access-groups'] = access_groups
    return provision_entitlements


def recodesign(app, provision, identity, dryrun=False):
    """
    ReCodeSign a given app with a given provision and identity pair.
    """
    # embeding a new provisioning profile
    if not dryrun:
        shutil.copyfile(provision['filename'], app['provision']['filename'])

    # generate a new entitlements
    entitlements_dict = generate_entitlements(provision['entitlements'], app)
    entitlements = tempfile.NamedTemporaryFile(suffix=".plist", delete=False)
    entitlements.write(write_plist_to_string(entitlements_dict))
    entitlements.close()

    # recodesign
    command = 'codesign {dryrun} -f -s "{identity}" --entitlements {entitlements} ' \
              '--preserve-metadata=resource-rules {app}'

    p = subprocess.Popen(command.format(
        dryrun='--dryrun' if dryrun else '',
        identity=identity,
        entitlements=entitlements.name,
        app=app['filename']
    ), shell=True, stderr=subprocess.PIPE)

    p.wait()

    print "-=-=-=-=-=-=-=-run command-=-=-=-=-=-=-=-"
    print command.format(
        dryrun='--dryrun' if dryrun else '',
        identity=identity,
        entitlements=entitlements.name,
        app=app['filename']
    )
    if p.stderr:
        print "-=-=-=-=-=-=-=-command error or Warning-=-=-=-=-=-=-=-"
        print p.stderr.read()
        pass

    os.unlink(entitlements.name)


def show_provision_info(provision):
    """
    Print information about a given provisioning profile.
    """
    print('')
    print('     Provision :: %s' % os.path.basename(provision['filename']))
    print('')
    print('          UUID:   %s' % provision['uuid'])
    print('          Name:   %s' % provision['name'])
    print('        App ID:   %s' % provision['app_id'])
    print('       APS Env:   %s' % provision['aps_env'])
    print('    Task Allow:   %s' % provision['task_allow'])
    print('')


def main():
    """
    iResign's entry point.
    """
    # parse command line arguments
    arguments = parse_arguments()

    # get main three components for recodesigning
    ipa = arguments.ipa

    appRootPath = old_ipa_process(ipa)

    for dir in os.listdir(appRootPath):
        if '.app' in dir:
            applicationPath = appRootPath + '/' + dir
            break

    if not applicationPath.strip():
        print 'no app file in ipa'
        sys.exit()
    else:
        application = read_application(applicationPath)

    provision = read_provisioning_profile(arguments.provisioning_profile)
    identity = arguments.identity

    # print verbose information
    if arguments.verbose:
        show_provision_info(application['provision'])
        show_provision_info(provision)

    # recodesigning!
    print('* Recodesigning :: {old} => {new}'.format(
        old=application['provision']['name'], new=provision['name']))
    recodesign(application, provision, identity, arguments.dryrun)

    print('resign done!')

    file_to_ipa(appRootPath)


def parse_arguments():
    """
    Parse command line arguments, check and return them if all is ok.
    """
    parser = argparse.ArgumentParser(
        description='iResign is a tool for recodesigning iOS applications.')

    parser.add_argument('ipa', help='the path to the iOS application ipa file')

    parser.add_argument('provisioning_profile',
                        help='the path to the provisioning profile')

    parser.add_argument('identity', default='iPhone Developer',
                        help='the signing identity')

    parser.add_argument('-d', '--dryrun', dest='dryrun', action='store_true',
                        help='test posibility of recodesigning')

    parser.add_argument('-v', '--verbose', dest='verbose', action='store_true',
                        help='show info about provisioning profiles')

    return parser.parse_args()


def old_ipa_process(ipa_path):
    path = os.path.split(ipa_path)[0]
    tmpPath = path + '/iresign_tmp'

    zipName = '/ipa.zip'
    zipPath = tmpPath + zipName

    try:
        shutil.rmtree(tmpPath)
    except:
        pass

    os.mkdir(tmpPath)

    if os.path.exists(ipa_path):
        shutil.copyfile(ipa_path, zipPath)
    else:
        print 'ipa not exist'
        sys.exit()

    fileDir = zip_to_file(zipPath)
    return fileDir


def zip_to_file(zip_path):
    path = os.path.split(zip_path)[0]

    r = zipfile.is_zipfile(zip_path)
    if r:
        fz = zipfile.ZipFile(zip_path, 'r')
        for file in fz.namelist():
            fz.extract(file, path)
    else:
        print('This file is not zip file')

    return path + '/Payload'


def file_to_ipa(file_path):
    try:
        import zlib
        compression = zipfile.ZIP_DEFLATED
    except:
        compression = zipfile.ZIP_STORED

    path = file_path
    start = path.rfind(os.sep) + 1
    zipPath = path + '.zip'
    z = zipfile.ZipFile(zipPath, mode="w", compression=compression)
    try:
        for dirpath, dirs, files in os.walk(path):
            for file in files:
                if file == zipPath or file == "zip.py":
                    continue
                z_path = os.path.join(dirpath, file)
                z.write(z_path, z_path[start:])
        z.close()
    except:
        if z:
            z.close()

    os.rename(zipPath, path + '.ipa')
    shutil.rmtree(path)

    ipaZipPath = os.path.split(path)[0] + '/ipa.zip'
    os.remove(ipaZipPath)

    print 'new ipa is created:' + path + '.ipa'

if __name__ == '__main__':
    main()

    print 'iresign finish!'
