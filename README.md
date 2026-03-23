# Getting Started

You have a new team application repository!

If you are seeing this in your README you likely have not ran the initialization script [init.sh](./init.sh). Read the below readme for instructions on how to get started.


## Running init.sh

the `init.sh` script will setup this repository for the specified project type. The project name will be inferred by based off the git repository name.

```
./init.sh maven
```

### Running outside of git

Run init.sh with a project name and path. This can also be used for testing out changes to the templates

```
./init.sh maven myproject-name /path/to/project/dir
```

Testing out local changes
```
./init.sh maven testprojectname ./target
```