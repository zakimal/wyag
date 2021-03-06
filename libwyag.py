import argparse  # for parsing commandline arguments
import sys
import collections  # for OrderedDict
import configparser  # for parsing .ini config file
import hashlib  # for SHA-1
import os  # for handling paths
import re  # for regular expression
import zlib  # for compression

argparser = argparse.ArgumentParser(description="The stupid content tracker")

argsubparsers = argparser.add_subparsers(title="Commands", dest="command")
argsubparsers.required = True
argsp = argsubparsers.add_parser(
    "init", help="Initialize a new, empty repository.")
argsp.add_argument("path", metavar="directory", nargs="?",
                   default=".", help="Where to create the repository.")
argsp = argsubparsers.add_parser(
    "cat-file", help="Provide content of repository objects")
argsp.add_argument("type", metavar="type", choices=[
                   "blob", "commit", "tag", "tree"], help="Specify the type")
argsp.add_argument("object", metavar="object", help="The object to display")
argsp = argsubparsers.add_parser(
    "hash-object", help="Compute object ID and optionally creates a blob from a file")
argsp.add_argument("-t", metavar="type", dest="type", choice=[
                   "blob", "commit", "tag", "tree"], default="blob", help="Specify the type")
argsp.add_argument("-w", dest="write", action="store_true",
                   help="Actually write the object into the database")
argsp.add_argument("path", help="Read object from <file>")
argsp = argsubparsers.add_parser(
    "log", help="Display history of a given commit")
argsp.add_argument("commit", default="HEAD", nargs="?",
                   help="Commit to start at")
argsp = argsubparsers.add_parser("ls-tree", help="Pretty print a tree object")
argsp.add_argument("object", help="The object to show")
argsp = argsubparsers.add_parser(
    "checkout", help="Checkout a commit inside of a directory")
argsp.add_argument("commit", help="The commit or tree to checkout")
argsp.add_argument("path", help="The empty directory to checkout on")
argsp = argsubparsers.add_parser("show-ref", help="List references")
argsp = argsubparsers.add_parser("tag", help="List and create tags")
argsp.add_argument("-a", action="store_true",
                   dest="create_tag_object", help="Whether to create a tag object")
argsp.add_argument("name", nargs="?", help="The new tag's name")
argsp.add_argument("object", default="HEAD", nargs="?",
                   help="The object the nte tag will point to")
argsp = argsubparsers(
    "rev-parse", help="Parse revision (or other objects) identifiers")
argsp.add_argument("--wyag-type", metavar="type", dest="type",
                   choices=["blob", "commit", "tag", "tree"], default=None, help="Specify the expected type")
argsp.add_argument("name", help="The name to parse")


def main(argv=sys.argv[1:]):
    args = argparser.parse_args(argv)

    if args.command == "add":
        cmd_add(args)
    elif args.command == "cat-file":
        cmd_cat_file(args)
    elif args.command == "checkout":
        cmd_checkout(args)
    elif args.command == "commit":
        cmd_commit(args)
    elif args.command == "hash-object":
        cmd_hash_object(args)
    elif args.command == "init":
        cmd_init(args)
    elif args.command == "log":
        cmd_log(args)
    elif args.command == "ls-tree":
        cmd_ls_tree(args)
    elif args.command == "merge":
        cmd_merge(args)
    elif args.command == "rebase":
        cmd_rebase(args)
    elif args.command == "rev-parse":
        cmd_rev_parse(args)
    elif args.command == "rm":
        cmd_rm(args)
    elif args.command == "show-ref":
        cmd_show_ref(args)
    elif args.command == "tag":
        cmd_tag(args)


class GitRepository(object):
    """A git repository"""

    worktree = None
    gitdir = None  # .git
    conf = None  # .git/config

    def __init__(self, path, force=False):
        self.worktree = path
        self.gitdir = os.path.join(path, ".git")

        if not (force or os.path.isdir(self.gitdir)):
            raise Exception("Not a Git repository {}".format(path))

        self.conf = configparser.ConfigParser()
        cf = repo_file(self, "config")

        if cf and os.path.exists(cf):
            self.conf.read([cf])
        elif not force:
            raise Exception("Configuration file missing")

        if not force:
            # core.repositoryformatversion
            vers = int(self.conf.get("core", "repositoryformatversion"))
            if vers != 0:
                raise Exception(
                    "Unsupported repositoryformatversion {}".format(vers))


def repo_path(repo, *path):
    """Compute path under repo's gitdir"""
    return os.path.join(repo.gitdir, *path)


def repo_file(repo, *path, mkdir=False):
    """Same as repo_path, but create dirname(*path) if absent. For example, repo_file(r, \"refs\", \"remotes\", \" origin\". \"HEAD\") will create .git/refs/remotes/origin."""
    if repo_dir(repo, *path[:-1], mkdir=mkdir):
        return repo_path(repo, *path)


def repo_dir(repo, *path, mkdir=False):
    """Same as repo_path, but mkdir *path if absent if mkdir."""
    path = repo_path(repo, *path)

    if os.path.exists(path):
        if os.path.isdir(path):
            return path
        else:
            raise Exception("Not a directory {}".format(path))

    if mkdir:
        os.makedirs(path)
        return path
    else:
        return None


def repo_create(path):
    """Create a new repository at path"""
    repo = GitRepository(path, force=True)

    # First, we make sure that the path either does not exists or is an empty dir.
    if os.path.exists(repo.worktree):
        if not os.path.isdir(repo.worktree):
            raise Exception("{} is not a directory!".format(path))
        if os.listdir(repo.worktree):
            raise Exception("{} is not empty".format(path))
    else:
        os.makedirs(repo.worktree)

    assert(repo_dir(repo, "branches", mkdir=True))  # .git/branches/
    assert(repo_dir(repo, "objects", mkdir=True))  # .git/objects/
    assert(repo_dir(repo, "refs", "tags", mkdir=True))  # .git/refs/tags/
    assert(repo_dir(repo, "refs", "heads", mkdir=True))  # .git/refs/heads/

    # .git/description
    with open(repo_file(repo, "description"), "w") as f:
        f.write(
            "Unnamed repository: edit this file 'description' to name the repository.\n")

    # .git/HEAD
    with open(repo_file(repo, "HEAD"), "w") as f:
        f.write("ref: refs/heads/main\n")

    # .git/config
    with open(repo_file(repo, "config"), "w") as f:
        config = repo_default_config()
        config.write(f)

    return repo


def repo_default_config():
    ret = configparser.ConfigParser()

    ret.add_section("core")
    ret.set("core", "repositoryformatversion", "0")
    ret.set("core", "filemode", "false")
    ret.set("core", "bare", "false")

    return ret


def repo_find(path=".", required=True):
    path = os.path.realpath(path)

    if os.path.isdir(os.path.join(path, ".git")):
        return GitRepository(path)

    # If we have not returned, recurse in parent.
    parent = os.path.realpath(os.path.join(path, ".."))

    if parent == path:  # base case
        if required:
            raise Exception("No git directory.")
        else:
            return None

    return repo_find(parent, required=required)


class GitObject(object):
    repo = None

    def __init__(self, repo, data=None):
        self.repo = repo
        if data != None:
            self.deserialize(data)

    def serialize(self):
        """This function MUST be implemented by subclasses.
        It must read the object's contents from self.data, a byte string, and do whatever it takes to covert it into a meaningful representation. What exactly that means depends on each subclass."""
        raise Exception("Unimplemented!")

    def deserialize(self, data):
        raise Exception("Unimplemented!")


class GitBlob(GitObject):
    fmt = b'blob'

    def serialize(self):
        return self.blobdata

    def deserialize(self, data):
        self.blobdata = data


class GitCommit(GitObject):
    fmt = b'commit'

    def deserialize(self, data):
        self.kvlm = kvlm_parse(data)

    def serialize(self):
        return kvlm_serialize(self.kvml)


class GitTree(GitObject):
    fmt = b'tree'

    def deserialize(self, data):
        self.items = tree_parse(data)

    def serialize(self):
        return tree_serialize(self)


class GitTreeLeaf(object):
    def __init__(self, mode, path, sha):
        self.mode = mode
        self.path = path
        self.sha = sha


class GitTag(GitCommit):
    fmt = b'tag'


class GitIndexEntry(object):
    # The last time a file's metadata changed.  This is a tuple (seconds, nanoseconds)
    ctime = None

    # The last time a file's data changed.  This is a tuple (seconds, nanoseconds)
    mtime = None

    # The ID of device containing this file
    dev = None

    # The file's inode number
    ino = None

    # The object type, either b1000 (regular), b1010 (symlink), b1110 (gitlink).
    mode_type = None

    # The object permissions, an integer.
    mode_perms = None

    # User ID of owner
    uid = None

    # Group ID of ownner
    gid = None

    # Size of this object, in bytes
    size = None

    # The object's hash as a hex string
    obj = None

    flag_assume_valid = None
    flag_extended = None
    flag_stage = None

    # Length of the name if < 0xFFF (yes, three Fs), -1 otherwise
    flag_name_length = None

    name = None


def object_read(repo, sha):
    """Read object sha from Git repository repo. Return a GitObject whose exact type depends on the object."""
    path = repo_file(repo, "objects", sha[0:2], sha[2:])

    # object format
    # +----------+--------------------------------------------------------------------+
    # | address  |                                                                    |
    # +----------+--------------------------------------------------------------------+
    # | 00000000 | 63 6f 6d 6d 69 74 20 31  30 38 36 00 74 72 65 65 | commit 1086.tree|
    # | 00000010 | 20 32 39 66 66 31 36 63  39 63 31 34 65 32 36 35 | 29ff16c9c14e265 |
    # | 00000020 | 32 62 32 32 66 38 62 37  38 62 62 30 38 61 35 61 | 2b22f8b78bb08a5a|
    # +----------+--------------------------------------------------------------------+

    with open(path, "rb") as f:
        raw = zlib.decompress(f.read())

        x = raw.find(b' ')
        fmt = raw[0:x]  # object type

        y = raw.find(b'\x00', x)
        size = int(raw[x:y].decode("ascii"))
        if size != len(raw) - y - 1:
            raise Exception("Malformed object {}: bad length".format(sha))

        if fmt == b'commit':
            c = GitCommit
        elif fmt == b'tree':
            c = GitTree
        elif fmt == b'tag':
            c = GitTag
        elif fmt == b'blob':
            c = GitBlob
        else:
            raise Exception("Unknown type {} for object {}".format(
                fmt.decode("ascii"), sha))

        return c(repo, raw[y+1:])


def object_write(obj, actually_write=True):
    data = obj.serialize()
    result = obj.fmt + b' ' + str(len(data)).encode() + b'\x00' + data
    sha = hashlib.sha1(result).hexdigest()

    if actually_write:
        path = repo_file(obj.repo, "objects",
                         sha[0:2], sha[2:], mkdir=actually_write)

        with open(path, 'wb') as f:
            f.write(zlib.compress(result))

    return sha


def object_resolve(repo, name):
    """Resolve name to an object hash in repo.
    This function is aware of:
    - the HEAD literal
    - short and long hashes
    - tags
    - branches
    - remote branches"""

    candidates = list()
    hashRE = re.compile(r"^[0-9A-Fa-f]{1,16}$")
    smallHashRE = re.compile(r"^[0-9A-Fa-f]{1,16}$")

    if not name.strip():
        return None

    if name == "HEAD":
        return [ref_resolve(repo, "HEAD")]

    if hashRE.match(name):
        if len(name) == 40:
            return [name.lower()]
        elif 4 <= len(name):
            name = name.lower()
            prefix = name[0:2]
            path = repo_dir(repo, "objects", prefix, mkdir=False)
            if path:
                rem = name[2:]
                for f in os.listdir(path):
                    if f.startswith(rem):
                        candidates.append(prefix + f)
    return candidates


def object_find(repo, name, fmt=None, follow=True):
    sha = object_resolve(repo, name)

    if not sha:
        raise Exception("No such reference {0}.".format(name))

    if len(sha) > 1:
        raise Exception(
            "Ambiguous reference {0}: Candidates are:\n - {1}.".format(name,  "\n - ".join(sha)))

    sha = sha[0]

    if not fmt:
        return sha

    while True:
        obj = object_read(repo, sha)

        if obj.fmt == fmt:
            return sha

        if not follow:
            return None

        # Follow tags
        if obj.fmt == b'tag':
            sha = obj.kvlm[b'object'].decode("ascii")
        elif obj.fmt == b'commit' and fmt == b'tree':
            sha = obj.kvlm[b'tree'].decode("ascii")
        else:
            return None


def kvlm_parse(raw, start=0, dct=None):
    # Key-Value List with Message
    if not dct:
        dct = collections.OrderedDict()

    spc = raw.find(b' ', start)  # space
    nl = raw.find(b'\n', start)  # new line

    # if space appers before newline, there is a keyword

    # basecase
    # if newline appers first (or there is no space at all, in which case return -1), there is a blank line. A blank line means the remainder of the data is message.
    if spc < 0 or nl < spc:
        assert(nl == start)
        dct[b''] = raw[start+1:]  # '': message...
        return dct

    # read keyword
    key = raw[start:spc]

    # find the end of the value
    end = start
    while True:
        end = raw.find(b'\n', end + 1)
        if raw[end + 1] != ord(' '):
            break

    # read value
    value = raw[spc+1:end].replace(b'\n', b'\n')

    if key in dct:  # do not overwrite the existing data
        if type(dct[key]) == list:
            dct[key].append(value)
        else:
            dct[key] = [dct[key], value]
    else:
        dct[key] = value

    return kvlm_parse(raw, start=end+1, dct=dct)


def kvlm_serialize(kvlm):
    ret = b''

    for k in kvlm.keys():
        if k == b'':
            continue  # skip the message itself
        val = kvlm[k]
        if type(val) != list:
            val = [val]

        for v in val:
            ret += k + b' ' + (v.replace(b'\n', b'\n')) + b'\n'

    ret += b'\n' + kvlm[b'']  # append message

    return ret


def tree_parse(raw):
    pos = 0
    max = len(raw)
    ret = list()
    while pos < max:
        pos, data = tree_parse_one(raw, pos)
        ret.append(data)

    return ret


def tree_parse_one(raw, start=0):
    # format: [mode] space [path] 0x00 [sha-1]
    x = raw.find(b' ', start)
    assert(x - start == 5 or x - start == 6)

    mode = raw[start:x]

    y = raw.find(b'\x00', x)
    path = raw[x+1:y]

    sha = hex(int.from_bytes(raw[y+1:y+21], "big"))[2:]

    return y + 21, GitTreeLeaf(mode, path, sha)


def tree_serialize(obj):
    ret = b''
    for i in obj.items:
        ret += i.mode
        ret += b' '
        ret += i.path
        ret += b'\x00'
        sha = int(i.sha, 16)
        ret += sha.to_bytes(20, byteorder="big")
    return ret


def tree_checkout(repo, tree, path):
    for item in tree.item:
        obj = object_read(repo, item.sha)
        dst = os.path.join(path, item.path)

        if obj.fmt == b'tree':
            os.mkdir(dst)
            tree_checkout(repo, obj, dst)
        elif obj.fmt == b'blob':
            with open(dst, 'wb') as f:
                f.write(obj.blobdata)


def ref_resolve(repo, ref):
    with open(repo_file(repo, ref), 'r') as f:
        data = f.read()[:-1]  # trim '\n'
    if data.startswith("ref: "):
        return ref_resolve(repo, data[5:])
    else:
        return data


def ref_list(repo, path=None):
    if not path:
        path = repo_dir(repo, "refs")

    ret = collections.OrderedDict()

    for f in sorted(os.listdir(path)):
        can = os.path.join(path, f)
        if os.path.isdir(can):
            ret[f] = ref_list(repo, can)
        else:
            ret[f] = ref_resolve(repo, can)

    return ret

#############################################################
# wyag init
# usage: wyag init <path>
#############################################################


def cmd_init(args):
    repo_create(args.path)

#############################################################
# wyag cat-file
# usage: wyag cat-file <type> <object>
#############################################################


def cmd_cat_file(args):
    repo = repo_find()
    cat_file(repo, args.object, fmt=args.type.encode())


def cat_file(repo, obj, fmt=None):
    obj = object_read(repo, object_find(repo, obj, fmt=fmt))
    sys.stdout.buffer.write(obj.serialize())

#############################################################
# wyag hash-object
# usage: wyag hash-object [-w] [-t <type>] <file>
#############################################################


def cmd_hash_object(args):
    if args.write:
        repo = GitRepository(".")
    else:
        repo = None

    with open(args.path, 'rb') as f:
        sha = object_hash(f, args.type.encode(), repo)
        print(sha)


def object_hash(f, fmt, repo=None):
    data = f.read()

    if fmt == b'commit':
        obj = GitCommit(repo, data)
    elif fmt == b'tree':
        obj = GitTree(repo, data)
    elif fmt == b'tag':
        obj = GitTag(repo, data)
    elif fmt == b'blob':
        obj = GitBlob(repo, data)
    else:
        raise Exception("Unknown type {}".format(fmt))

    return object_write(obj, repo)

#############################################################
# wyag log
# usage: wyag log <commit id>
#############################################################


def cmd_log(args):
    repo = repo_find()

    print("digraph wyaglog(")
    log_graphviz(repo, object_find(repo, args.commit), set())
    print(")")


def log_graphviz(repo, sha, seen):
    if sha in seen:
        return
    seen.add(sha)

    commit = object_read(repo, sha)
    assert(commit.fmt == b'commit')

    if not b'parent' in commit.kvlm.keys():
        return  # initial commit

    parents = commit.kvlm[b'parent']

    if type(parents) != list:
        parents = [parents]

    for p in parents:
        p = p.decode("ascii")
        print("c_{} -> c_{}".format(sha, p))
        log_graphviz(repo, p, seen)

#############################################################
# wyag ls-tree
# usage: wyag ls-tree <object id>
#############################################################


def cmd_ls_tree(args):
    repo = repo_find()
    obj = object_read(repo, object_find(repo, args.object, fmt=b'tree'))

    for item in obj.items:
        # <mode> <object type> <sha> \t <path>
        print("{} {} {}\t{}".format(
            "0" * (6 - len(item.mode)) + item.mode.decode("ascii"),
            object_read(repo, item.sha).fmt.decode("ascii"), item.sha,
            item.path.decode("ascii")))


#############################################################
# wyag checkout
# usage: wyag checkout <commit> <path>
#############################################################


def cmd_checkout(args):
    repo = repo_find()
    obj = object_read(repo, object_find(repo, args.commit))

    if obj.fmt == b'commit':
        obj = object_read(repo, obj.kvlm[b'tree'].decode("ascii"))

    if os.path.exists(args.path):
        if not os.path.isdir(args.path):
            raise Exception("Not a directory {}".format(args.path))
        if os.listdir(args.path):
            raise Exception("Not empty {}".format(args.path))
    else:
        os.makedirs(args.path)

    tree_checkout(repo, obj, os.path.realpath(args.path).encode())

#############################################################
# wyag show-ref
# usage: wyag show-ref
#############################################################


def cmd_show_ref(args):
    repo = repo_find()
    refs = ref_list(repo)
    show_ref(repo, refs, prefix="refs")


def show_ref(repo, refs, with_hash=True, prefix=""):
    for k, v in refs.items():
        if type(v) == str:
            print("{}{}{}".format(
                v + " " if with_hash else "",
                prefix + "/" if prefix else "",
                k
            ))
        else:
            show_ref(repo, v, with_hash=with_hash, prefix="{}{}{}".format(
                prefix, "/" if prefix else "", k))

#############################################################
# wyag tag
# usage: wyag tag                         # list all tags
# usage: wyag tag <name> [<object id>]    # create a new lightweight tag <name>,
#                                         # pointing to HEAD (default) or <object id>
# usage: wyag tag -a <name> [<object id>] # create a new tag object <name>,
#                                         # pointing to HEAD (default) or <object id>
#############################################################


def cmd_tag(args):
    repo = repo_find()
    if args.name:
        tag_create(args.name, args.object,
                   type="object" if args.create_tag_object else "ref")
    else:
        refs = ref_list(repo)
        show_ref(repo, refs["tags"], with_hash=False)

# TODO: implement tag_create()
# def tag_create()

#############################################################
# wyag rev-parse
# usage: wyag rev-parse [--wyag-type <type>] <name>
#############################################################


def cmd_rev_parse(args):
    if args.type:
        fmt = args.type.encode()

    repo = repo_find()

    print(object_find(repo, args.name, args.type, follow=True))
