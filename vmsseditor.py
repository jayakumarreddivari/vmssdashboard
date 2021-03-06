'''VMSS Editor - Azure VM Scale Set management tool'''

import json
import os
import sys
import threading
import tkinter as tk
from time import sleep, strftime
from tkinter import messagebox

import subscription
import vmss

# size and color defaults
btnwidth = 14
entrywidth = 15
if os.name == 'posix':  # Mac OS
    geometry1 = '700x140'
    geometry100 = '700x450'
    geometry1000 = '1500x940'
    list_width = 14
    status_width = 98
    canvas_width100 = 690
    canvas_width1000 = 1300
else:
    geometry1 = '540x128'
    geometry100 = '540x440'
    geometry1000 = '1300x950'
    list_width = 8
    status_width = 67
    canvas_width100 = 520
    canvas_width1000 = 1230

canvas_height100 = 195
canvas_height1000 = 700
frame_bgcolor = '#B0E0E6'
canvas_bgcolor = '#F0FFFF'
btncolor = '#F8F8FF'

# Load Azure app defaults
try:
    with open('vmssconfig.json') as configFile:
        config_data = json.load(configFile)
except FileNotFoundError:
    sys.exit('Error: Expecting vmssconfig.json in current folder')

sub = subscription.subscription(config_data['tenantId'], config_data['appId'],
                                config_data['appSecret'], config_data['subscriptionId'])
current_vmss = None
refresh_thread_running = False

def subidkeepalive():
    '''thread to keep access token alive'''
    while True:
        sleep(2000)
        sub.auth()
        current_vmss.update_token(sub.access_token)

def refresh_loop():
    '''thread to refresh details until provisioning is complete'''
    global refresh_thread_running
    # refresh large scale sets slower to avoid API throttling
    if current_vmss is not None:
        if current_vmss.singlePlacementGroup is False:
            sleep_time = 30
        else:
            sleep_time = 10

        while True:
            while refresh_thread_running is True:
                current_vmss.refresh_model()
                if current_vmss.status == 'Succeeded' or current_vmss.status == 'Failed':
                    refresh_thread_running = False
                sleep(sleep_time)
                vmssdetails()
            sleep(10)

def rolling_upgrade_engine(batchsize, pausetime, vmbyfd_list):
    '''rolling upgrade thread'''
    global refresh_thread_running
    batch_count = 0 # to give user a running status update
    # loop through all VMs
    num_vms_to_upgrade = len(vmbyfd_list)
    upgrade_index = 0 # running count of VMs updated or in batch to update
    while upgrade_index < num_vms_to_upgrade:
        batch_count += 1
        # determine the next batch of VM IDs
        batch_list = []
        for batch_index in range(batchsize):
            batch_list.append(vmbyfd_list[upgrade_index][0])
            upgrade_index += 1
            if upgrade_index == num_vms_to_upgrade:
                break

        # do an upgrade on the batch
        statusmsg('Upgrading batch ' + str(batch_count))
        current_vmss.upgradevm(json.dumps(batch_list))
        statusmsg('Batch ' + str(batch_count) + ' status: ' + current_vmss.status)
        refresh_thread_running = True

        # wait for upgrade to complete
        statusmsg('Batch ' + str(batch_count) + ' upgrade in progress')
        while refresh_thread_running is True:
            sleep(1)
        print('Batch ' + str(batch_count) + ' complete')
        # wait for pausetime
        sleep(pausetime)
    statusmsg('Rolling upgrade complete. Batch count: ' + str(batch_count))

# start timer thread
timer_thread = threading.Thread(target=subidkeepalive, args=())
timer_thread.daemon = True
timer_thread.start()

# start refresh thread
refresh_thread = threading.Thread(target=refresh_loop, args=())
refresh_thread.daemon = True
refresh_thread.start()


def assign_color_to_power_state(powerstate):
    '''visually represent VM powerstate with a color'''
    if powerstate == 'running':
        return 'green'
    elif powerstate == 'stopped':
        return 'red'
    elif powerstate == 'starting':
        return 'yellow'
    elif powerstate == 'stopping':
        return 'orange'
    elif powerstate == 'deallocating':
        return 'grey'
    elif powerstate == 'deallocated':
        return 'black'
    else: # unknown
        return 'blue'

def draw_grid(originx, originy, row_height, ystart, xend, groupId):
    '''draw a grid to delineate fault domains and update domains on the VMSS heatmap'''
    vmcanvas.create_text(originx + 180, originy + 10, text='Placement group: ' + groupId)
    # horizontal lines for UDs
    for y in range(5):
        ydelta = y * row_height
        vmcanvas.create_text(originx + 15, originy + ydelta + 50, text='UD ' + str(y))
        if y < 4:
            vmcanvas.create_line(originx + 35, originy + ystart + ydelta, originx + 415, \
                originy + ystart + ydelta)

    # vertical lines for FDs
    for x in range(5):
        xdelta = x * 80
        vmcanvas.create_text(originx + 45 + xdelta, originy + 30, text='FD ' + str(x))
        if x < 4:
            vmcanvas.create_line(originx + 110 + xdelta, originy + 40, originx + 110 + xdelta, \
                originy + xend, dash=(4, 2))

def draw_vms():
    '''draw a heat map for the VMSS VMs'''
    xval = 35
    yval = 40
    diameter = 10
    row_height = 27
    ystart = 60
    xend = 170
    originx = 0
    originy = 0
    current_vmss.set_domain_lists()
    vmcanvas.delete("all")
    if current_vmss.singlePlacementGroup is False and len(current_vmss.pg_list) > 1:
        vbar.pack(side=tk.RIGHT, fill=tk.Y)
        vbar.config(command=vmcanvas.yview)
        vmcanvas.config(yscrollcommand=vbar.set)
        vmcanvas.pack(side=tk.LEFT, expand=True, fill=tk.BOTH)
        fontsize = 4
    else:
        fontsize = 5
    pgcount = 0
    for placementGroup in current_vmss.pg_list:
        draw_grid(originx, originy, row_height, ystart, xend, placementGroup['guid'])
        matrix = [[0 for x in range(5)] for y in range(5)]
        for vm in placementGroup['vm_list']:
            instance_id = vm[0]
            fd = vm[1]
            ud = vm[2]
            powerstate = vm[3]
            statuscolor = assign_color_to_power_state(powerstate)

            # the purpose of this is to build up multiple rows of 5 in each UD/FD
            row = matrix[ud][fd] // 5
            xdelta = fd * 80 + (matrix[ud][fd] - row * 5) * 15
            ydelta = ud * row_height + row * 30

            # colored circle represents machine power state
            vmcanvas.create_oval(originx + xval + xdelta, originy + yval + ydelta,
                                 originx + xval + xdelta + diameter,
                                 originy + yval + ydelta + diameter, fill=statuscolor)
            # print VM ID under each circle
            vmcanvas.create_text(originx + xval + xdelta + 7, originy + yval + ydelta + 15,
                                 font=("Purisa", fontsize), text=instance_id)
            matrix[ud][fd] += 1
        originx += 425
        pgcount += 1
        if pgcount % 3 == 0:
            originy += 170
            originx = 0
    vmcanvas.update_idletasks() # refresh the display
    sleep(0.01) # add a little nap seems to make the display refresh more reliable

def getfds():
    '''build a list of fault domains'''
    fd = int(selectedfd.get())
    fdinstancelist = []
    # loop through placement groups
    for pg in current_vmss.pg_list:
        for entry in pg['fd_dict'][fd]:
            fdinstancelist.append(entry[0])  # entry[0] is the instance id
    # build list of FDs
    return fdinstancelist


def startfd():
    '''start all the VMs in a fault domain'''
    global refresh_thread_running
    fdinstancelist = getfds()
    current_vmss.startvm(json.dumps(fdinstancelist))
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def powerfd():
    '''power off all the VMs in a fault domain'''
    global refresh_thread_running
    fdinstancelist = getfds()
    current_vmss.poweroffvm(json.dumps(fdinstancelist))
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def reimagefd():
    '''reimage all the VMs in a fault domain'''
    global refresh_thread_running
    fdinstancelist = getfds()
    current_vmss.reimagevm(json.dumps(fdinstancelist))
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def upgradefd():
    '''upgrade all the VMs in a fault domain'''
    global refresh_thread_running
    fdinstancelist = getfds()
    current_vmss.upgradevm(json.dumps(fdinstancelist))
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def rollingupgrade():
    '''initiate a rolling upgrade to the latest model'''
    batchsize = int(batchtext.get())
    pausetime = int(pausetext.get())

    # get list of VMs ordered by FD - get this by concatenating the vmss fd_dict into a single list
    vmbyfd_list = []
    for fdval in range(5):
        for pg in current_vmss.pg_list:
            vmbyfd_list += pg['fd_dict'][fdval]

    # launch rolling update thread
    rolling_upgrade_thread = threading.Thread(target=rolling_upgrade_engine, \
        args=(batchsize, pausetime, vmbyfd_list,))
    rolling_upgrade_thread.daemon = True
    rolling_upgrade_thread.start()


def reimagevm():
    '''reimage a VM or list of VMs'''
    global refresh_thread_running
    vmid = vmtext.get()
    vmstring = '["' + vmid + '"]'
    current_vmss.reimagevm(vmstring)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def upgradevm():
    '''upgrade a VM or list of VMs'''
    global refresh_thread_running
    vmid = vmtext.get()
    vmstring = '["' + vmid + '"]'
    current_vmss.upgradevm(vmstring)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def deletevm():
    '''delete a VM or list of VMs'''
    global refresh_thread_running
    vmid = vmtext.get()
    vmstring = '["' + vmid + '"]'
    current_vmss.deletevm(vmstring)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def startvm():
    '''start a VM or list of VMs'''
    global refresh_thread_running
    vmid = vmtext.get()
    vmstring = '["' + vmid + '"]'
    current_vmss.startvm(vmstring)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def restartvm():
    '''restart a VM or list of VMs'''
    global refresh_thread_running
    vmid = vmtext.get()
    vmstring = '["' + vmid + '"]'
    current_vmss.restartvm(vmstring)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def deallocvm():
    '''stop dealloc a VM or list of VMs'''
    global refresh_thread_running
    vmid = vmtext.get()
    vmstring = '["' + vmid + '"]'
    current_vmss.deallocvm(vmstring)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def poweroffvm():
    '''power off a VM or list of VMs'''
    global refresh_thread_running
    vmid = vmtext.get()
    vmstring = '["' + vmid + '"]'
    current_vmss.poweroffvm(vmstring)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


# begin tkinter components
root = tk.Tk()  # Makes the window
root.wm_title("Azure VM Scale Set Editor")
root.geometry(geometry1)
root.configure(background=frame_bgcolor)
root.wm_iconbitmap('vmss.ico')
topframe = tk.Frame(root, bg=frame_bgcolor)
middleframe = tk.Frame(root, bg=frame_bgcolor)
selectedfd = tk.StringVar()
vmcanvas = tk.Canvas(middleframe, height=canvas_height100, width=canvas_width100,
                     scrollregion=(0, 0, canvas_width1000, canvas_height1000 + 110),
                     bg=canvas_bgcolor)
vbar = tk.Scrollbar(middleframe, orient=tk.VERTICAL)
vmframe = tk.Frame(root, bg=frame_bgcolor)
baseframe = tk.Frame(root, bg=frame_bgcolor)
topframe.pack(fill=tk.X)
middleframe.pack(fill=tk.X)

# Rolling upgrade operations - VM frame
batchsizelabel = tk.Label(vmframe, text='Batch size:', bg=frame_bgcolor)
batchtext = tk.Entry(vmframe, width=11, bg=canvas_bgcolor)
batchtext.delete(0, tk.END)
batchtext.insert(0, '1')
pausetimelabel = tk.Label(vmframe, text='Pause time:', bg=frame_bgcolor)
pausetext = tk.Entry(vmframe, width=11, bg=canvas_bgcolor)
pausetext.delete(0, tk.END)
pausetext.insert(0, '0')
rollingbtn = tk.Button(vmframe, text='Rolling upgrade', command=rollingupgrade, width=btnwidth,
                       bg=btncolor)

# FD operations - VM frame
fdlabel = tk.Label(vmframe, text='FD:', bg=frame_bgcolor)
fdoption = tk.OptionMenu(vmframe, selectedfd, '0', '1', '2', '3', '4')
fdoption.config(width=6, bg=btncolor, activebackground=btncolor)
fdoption["menu"].config(bg=btncolor)
reimagebtnfd = tk.Button(vmframe, text='Reimage', command=reimagefd, width=btnwidth, bg=btncolor)
upgradebtnfd = tk.Button(vmframe, text='Upgrade', command=upgradefd, width=btnwidth, bg=btncolor)
startbtnfd = tk.Button(vmframe, text='Start', command=startfd, width=btnwidth, bg=btncolor)
powerbtnfd = tk.Button(vmframe, text='Power off', command=powerfd, width=btnwidth, bg=btncolor)

# VM operations - VM frame
vmlabel = tk.Label(vmframe, text='VM:', bg=frame_bgcolor)
vmtext = tk.Entry(vmframe, width=11, bg=canvas_bgcolor)
reimagebtn = tk.Button(vmframe, text='Reimage', command=reimagevm, width=btnwidth, bg=btncolor)
vmupgradebtn = tk.Button(vmframe, text='Upgrade', command=upgradevm, width=btnwidth, bg=btncolor)
vmdeletebtn = tk.Button(vmframe, text='Delete', command=deletevm, width=btnwidth, bg=btncolor)
vmstartbtn = tk.Button(vmframe, text='Start', command=startvm, width=btnwidth, bg=btncolor)
vmrestartbtn = tk.Button(vmframe, text='Restart', command=restartvm, width=btnwidth, bg=btncolor)
vmdeallocbtn = tk.Button(vmframe, text='Dealloc', command=deallocvm, width=btnwidth, bg=btncolor)
vmpoweroffbtn = tk.Button(vmframe, text='Power off', command=poweroffvm, width=btnwidth,
                          bg=btncolor)
vmframe.pack(fill=tk.X)
baseframe.pack(fill=tk.X)

capacitytext = tk.Entry(topframe, width=entrywidth, bg=canvas_bgcolor)
vmsizetext = tk.Entry(topframe, width=entrywidth, bg=canvas_bgcolor)
skutext = tk.Entry(topframe, width=entrywidth, bg=canvas_bgcolor)
versiontext = tk.Entry(topframe, width=entrywidth, bg=canvas_bgcolor)
statustext = tk.Text(baseframe, height=1, width=status_width, bg=canvas_bgcolor)


def statusmsg(statusstring):
    '''output a status message to screen'''
    st_message = strftime("%Y-%m-%d %H:%M:%S ") + str(statusstring)
    if statustext.get(1.0, tk.END):
        statustext.delete(1.0, tk.END)
    statustext.insert(tk.END, st_message)


def displayvmss(vmssname):
    '''Display scale set details'''
    global current_vmss
    current_vmss = vmss.vmss(vmssname, sub.vmssdict[vmssname], sub.sub_id, sub.access_token)
    # capacity - row 0
    locationlabel = tk.Label(topframe, text=current_vmss.location, width=btnwidth, justify=tk.LEFT,
                             bg=frame_bgcolor)
    locationlabel.grid(row=0, column=1, sticky=tk.W)
    tk.Label(topframe, text='Capacity: ', bg=frame_bgcolor).grid(row=0, column=2)
    capacitytext.grid(row=0, column=3, sticky=tk.W)
    capacitytext.delete(0, tk.END)
    capacitytext.insert(0, str(current_vmss.capacity))
    scalebtn = tk.Button(topframe, text="Scale", command=scalevmss, width=btnwidth, bg=btncolor)
    scalebtn.grid(row=0, column=4, sticky=tk.W)

    # VMSS properties - row 1
    vmsizetext.grid(row=1, column=3, sticky=tk.W)
    vmsizetext.delete(0, tk.END)
    vmsizetext.insert(0, str(current_vmss.vmsize))
    vmsizetext.grid(row=1, column=0, sticky=tk.W)
    offerlabel = tk.Label(topframe, text=current_vmss.offer, width=btnwidth, justify=tk.LEFT,
                          bg=frame_bgcolor)
    offerlabel.grid(row=1, column=1, sticky=tk.W)
    skutext.grid(row=1, column=2, sticky=tk.W)
    skutext.delete(0, tk.END)
    skutext.insert(0, current_vmss.sku)
    versiontext.grid(row=1, column=3, sticky=tk.W)
    versiontext.delete(0, tk.END)
    versiontext.insert(0, current_vmss.version)
    updatebtn = tk.Button(topframe, text='Update model', command=updatevmss, width=btnwidth,
                          bg=btncolor)
    updatebtn.grid(row=1, column=4, sticky=tk.W)

    # more VMSS properties - row 2
    if current_vmss.overprovision == True:
        optext = "overprovision: true"
    else:
        optext = "overprovision: false"
    overprovisionlabel = tk.Label(topframe, text=optext, width=btnwidth, justify=tk.LEFT,
                                  bg=frame_bgcolor)
    overprovisionlabel.grid(row=2, column=0, sticky=tk.W)
    upgradepolicylabel = tk.Label(topframe, text=current_vmss.upgradepolicy + ' upgrade',
                                  width=btnwidth, justify=tk.LEFT, bg=frame_bgcolor)
    upgradepolicylabel.grid(row=2, column=1, sticky=tk.W)
    adminuserlabel = tk.Label(topframe, text=current_vmss.adminuser, width=btnwidth,
                              justify=tk.LEFT, bg=frame_bgcolor)
    adminuserlabel.grid(row=2, column=2, sticky=tk.W)
    compnameprefixlabel = tk.Label(topframe, text='Prefix: ' + current_vmss.nameprefix,
                                   width=btnwidth, justify=tk.LEFT, bg=frame_bgcolor)
    compnameprefixlabel.grid(row=2, column=3, sticky=tk.W)
    rglabel = tk.Label(topframe, text='RG: ' + current_vmss.rgname,
                       width=btnwidth, justify=tk.LEFT, bg=frame_bgcolor)
    rglabel.grid(row=2, column=4, sticky=tk.W)

    # vmss operations - row 3
    onbtn = tk.Button(topframe, text="Start", command=poweronvmss, width=btnwidth, bg=btncolor)
    onbtn.grid(row=3, column=0, sticky=tk.W)
    onbtn = tk.Button(topframe, text="Restart", command=restartvmss, width=btnwidth, bg=btncolor)
    onbtn.grid(row=3, column=1, sticky=tk.W)
    offbtn = tk.Button(topframe, text="Power off", command=poweroffvmss, width=btnwidth,
                       bg=btncolor)
    offbtn.grid(row=3, column=2, sticky=tk.W)
    deallocbtn = tk.Button(topframe, text="Stop Dealloc", command=deallocvmss, width=btnwidth,
                           bg=btncolor)
    deallocbtn.grid(row=3, column=3, sticky=tk.W)
    detailsbtn = tk.Button(topframe, text="Show Heatmap", command=vmssdetails, width=btnwidth,
                           bg=btncolor)
    detailsbtn.grid(row=3, column=4, sticky=tk.W)

    # status line
    statustext.pack()
    statusmsg(current_vmss.status)


def scalevmss():
    '''scale a scale set in or out'''
    global refresh_thread_running
    newcapacity = int(capacitytext.get())
    current_vmss.scale(newcapacity)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def updatevmss():
    '''Update a scale set to VMSS model'''
    global refresh_thread_running
    newsku = skutext.get()
    newversion = versiontext.get()
    newvmsize = vmsizetext.get()
    current_vmss.update_model(newsku=newsku, newversion=newversion, newvmsize=newvmsize)
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def poweronvmss():
    '''Power on a VM scale set'''
    global refresh_thread_running
    current_vmss.poweron()
    statusmsg(current_vmss.status)
    refresh_thread_running = True

def restartvmss():
    '''Restart' a VM scale set'''
    global refresh_thread_running
    current_vmss.restart()
    statusmsg(current_vmss.status)
    refresh_thread_running = True

def poweroffvmss():
    '''Power off a VM scale set'''
    global refresh_thread_running
    current_vmss.poweroff()
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def deallocvmss():
    '''Stop deallocate on a VM scale set'''
    global refresh_thread_running
    current_vmss.dealloc()
    statusmsg(current_vmss.status)
    refresh_thread_running = True


def vmssdetails():
    global vmsslist
    # refresh VMSS model details
    vmsslist = sub.get_vmss_list()
    '''Show VM scale set placement details'''
    # VMSS VM canvas - middle frame
    if current_vmss.singlePlacementGroup == True or len(current_vmss.pg_list) < 2:
        geometry2 = geometry100
        canvas_height = canvas_height100
        canvas_width = canvas_width100
    else:
        geometry2 = geometry1000
        canvas_height = canvas_height1000
        canvas_width = canvas_width1000
    root.geometry(geometry2)
    vmcanvas.config(height=canvas_height, width=canvas_width)
    vmcanvas.pack()
    looping = True
    nextLink = None
    while looping is True:
        current_vmss.grow_vm_instance_view(nextLink)
        draw_vms()
        if not 'nextLink' in current_vmss.vm_instance_view:
            looping = False
        else:
            nextLink = current_vmss.vm_instance_view['nextLink']

    # draw rollingframe components
    batchsizelabel.grid(row=0, column=1, sticky=tk.W)
    batchtext.grid(row=0, column=2, sticky=tk.W)
    pausetimelabel.grid(row=0, column=3, sticky=tk.W)
    pausetext.grid(row=0, column=4, sticky=tk.W)
    rollingbtn.grid(row=0, column=5, sticky=tk.W)

    # draw VM frame components
    fdlabel.grid(row=1, column=0, sticky=tk.W)
    fdoption.grid(row=1, column=1, sticky=tk.W)
    reimagebtnfd.grid(row=1, column=2, sticky=tk.W)
    upgradebtnfd.grid(row=1, column=3, sticky=tk.W)
    startbtnfd.grid(row=1, column=4, sticky=tk.W)
    powerbtnfd.grid(row=1, column=5, sticky=tk.W)
    vmlabel.grid(row=2, column=0, sticky=tk.W)
    vmtext.grid(row=2, column=1, sticky=tk.W)
    reimagebtn.grid(row=2, column=2, sticky=tk.W)
    vmupgradebtn.grid(row=2, column=3, sticky=tk.W)
    vmstartbtn.grid(row=2, column=4, sticky=tk.W)
    vmpoweroffbtn.grid(row=2, column=5, sticky=tk.W)
    vmdeletebtn.grid(row=3, column=2, sticky=tk.W)
    vmrestartbtn.grid(row=3, column=3, sticky=tk.W)
    vmdeallocbtn.grid(row=3, column=4, sticky=tk.W)

    # draw status frame
    statusmsg(current_vmss.status)

# start by listing VM Scale Sets
vmsslist = sub.get_vmss_list()
selectedvmss = tk.StringVar()
if len(vmsslist) > 0:
    selectedvmss.set(vmsslist[0])
    selectedfd.set('0')
    displayvmss(vmsslist[0])
    # create top level GUI components
    vmsslistoption = tk.OptionMenu(topframe, selectedvmss, *vmsslist, command=displayvmss)
    vmsslistoption.config(width=list_width, bg=btncolor, activebackground=btncolor)
    vmsslistoption["menu"].config()
    vmsslistoption.grid(row=0, column=0, sticky=tk.W)
else:
    messagebox.showwarning("Warning", "Your subscription:\n" + sub.sub_id +\
                           "\ncontains no VM Scale Sets")

root.mainloop()
