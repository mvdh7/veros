"""
=======================================================================
      solve two dimensional Possion equation
           A * dpsi = forc,  where A = nabla_h^2
      with Dirichlet boundary conditions
      used for streamfunction
=======================================================================
"""

import sys
import numpy as np
from scipy.linalg import lapack
from climate.boussinesq.external import solve_pressure, island
from climate.boussinesq import cyclic

def streamfunction_init():
    """
    =======================================================================
      prepare for island integrals
    =======================================================================
    """
    #integer :: allmap(1-onx:nx+onx,1-onx:ny+onx)
    #integer :: map(1-onx:nx+onx,1-onx:ny+onx)
    #integer :: kmt(1-onx:nx+onx,1-onx:ny+onx)
    #integer, parameter :: maxipp = 10000, mnisle = 1000
    #integer :: iperm(maxipp),jperm(maxipp),nippts(mnisle), iofs(mnisle)
    #integer :: isle,n,i,j,ij(2),max_boundary,dir(2),ijp(2),ijp_right(2)
    #logical :: cont,verbose ,converged
    #real*8 :: forc(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8 :: fpx(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8 :: fpy(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)

    if my_pe == 0:
        print 'Initializing streamfunction method'
    verbose = enable_congrad_verbose
    """
    -----------------------------------------------------------------------
     communicate kbot to get the entire land map
    -----------------------------------------------------------------------
    """
    kmt[...] = 0 # note that routine will modify kmt
    for j in xrange(js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe+1): #i=is_pe,ie_pe
            if kbot[i,j] > 0:
                kmt[i,j] = 5

    #MPI stuff
    #call pe0_recv_2D_int(nx,ny,kmt(1:nx,1:ny))
    #call pe0_bcast_int(kmt,(nx+2*onx)*(ny+2*onx))

    if enable_cyclic_x:
        for i in xrange(1, onx+1): #i=1,onx
            kmt[nx+i,:] = kmt[i  ,:]
            kmt[1-i,:] = kmt[nx-i+1,:]

    """
    -----------------------------------------------------------------------
     preprocess land map using MOMs algorithm for B-grid to determine number of islands
    -----------------------------------------------------------------------
    """
    if my_pe == 0:
        print ' starting MOMs algorithm for B-grid to determine number of islands'
    island.isleperim(kmt,allmap, iperm, jperm, iofs, nippts, nisle, nx+2*onx, ny+2*onx, mnisle, maxipp,my_pe,enable_cyclic_x,True)
    if enable_cyclic_x:
        for i in xrange(1, onx+1): #i=1,onx
            allmap[nx+i,:] = allmap[i  ,:]
            allmap[1-i,:] = allmap[nx-i+1,:]
    if my_pe == 0:
        showmap(1-onx,nx+onx,1-onx,ny+onx,  allmap)

    """
    -----------------------------------------------------------------------
     allocate variables
    -----------------------------------------------------------------------
    """
    max_boundary= 2*maxval(nippts[1:nisle])
    boundary = numpy.zeros((nisle, max_boundary, 2))
    line_dir = numpy.zeros((nisle, max_boundary, 2))
    nr_boundary = numpy.zeros(nisle)
    psin = numpy.zeros((ie_pe+onx+1-(is_pe-onx), je_pe+onx+1-(je_pe+onx), nisle))
    dpsin = numpy.zeros((nisle, 3))
    line_psin = numpy.zeros((nisle, nisle))

    for isle in xrange(1, nisle+1): #isle=1,nisle

        if my_pe == 0:
            print ' ------------------------'
            print ' processing island #',isle
            print ' ------------------------'

        """
        -----------------------------------------------------------------------
         land map for island number isle: 1 is land, -1 is perimeter, 0 is ocean
        -----------------------------------------------------------------------
        """
        kmt[kmt == 0] = 1
        island.isleperim(kmt,map, iperm, jperm, iofs, nippts, i, nx+2*onx, ny+2*onx, mnisle, maxipp,my_pe,enable_cyclic_x,False)
        if my_pe == 0 and verbose:
            showmap(1-onx,nx+onx,1-onx,ny+onx, map)

        """
        -----------------------------------------------------------------------
         find a starting point
        -----------------------------------------------------------------------
        """
        n=1
        # avoid starting close to cyclic bondaries
        (cont, ij, Dir) = avoid_cyclic_boundaries(Map, boundary)

        if not cont:
            (cont, ij, Dir) = avoid_cyclic_boundaries2(Map, boundary)

            if not cont:
                if my_pe == 0:
                    print 'found no starting point for line integral'
                sys.exit('in streamfunction_init')

        if my_pe == 0:
            print ' starting point of line integral is ',boundary[isle,n,:]
            print ' starting direction is ', Dir

        """
        -----------------------------------------------------------------------
         now find connecting lines
        -----------------------------------------------------------------------
        """
        line_dir[isle,n,:] = Dir
        n = 2
        boundary[isle,n,:] = [ij[0], ij[1]]
        cont = True
        while cont:
            """
            -----------------------------------------------------------------------
             consider map in front of line direction and to the right and decide where to go
            -----------------------------------------------------------------------
            """
            if Dir[0]== 0 and Dir[1]== 1:
                ijp      = [ij[0]  ,ij[1]+1] #north
                ijp_right= [ij[0]+1,ij[1]+1] #north
            if Dir[0]==-1 and Dir[1]== 0:
                ijp      = [ij[0]  ,ij[1]  ] #west
                ijp_right= [ij[0]  ,ij[1]+1] #west
            if Dir[0]== 0 and Dir[1]==-1:
                ijp      = [ij[0]+1,ij[1]  ] #south
                ijp_right= [ij[0]  ,ij[1]  ] #south
            if Dir[0]== 1 and Dir[1]== 0:
                ijp      = [ij[0]+1,ij[1]+1] #east
                ijp_right= [ij[0]+1,ij[1]  ] #east

            """
            -----------------------------------------------------------------------
              4 cases are possible
            -----------------------------------------------------------------------
            """

            if verbose and my_pe == 0:
                print ' '
                print ' position is  ',ij
                print ' direction is ',Dir
                print ' map ahead is ',Map[ijp[0],ijp[1]] , Map[ijp_right[0],ijp_right[1]]

            if Map[ijp[0],ijp[1]] == -1 and Map[ijp_right[0],ijp_right[1]] == 1:
                if verbose and my_pe == 0:
                    print ' go forward'
            elif Map[ijp[0],ijp[1]] == -1 and Map[ijp_right[0],ijp_right[1]] == -1:
                if verbose and my_pe == 0:
                    print ' turn right'
                Dir = [Dir[1],-Dir[0]]
            elif Map[ijp[0],ijp[1]] == 1 and Map[ijp_right[0],ijp_right[1]] == 1:
                if verbose and my_pe == 0:
                    print ' turn left'
                Dir =  [-Dir[1],Dir[0]]
            elif Map[ijp[0],ijp[1]] == 1 and Map[ijp_right[0],ijp_right[1]] == -1:
                if verbose and my_pe == 0:
                    print ' turn left'
                Dir =  [-Dir[1],Dir[0]]
            else:
                print 'unknown situation or lost track'
                for n in xrange(1, n+1): #n=1,n
                    print ' pos=',boundary[isle,n,:],' dir=',line_dir[isle,n,:]
                print ' map ahead is ',Map[ijp[0],ijp[1]] , Map[ijp_right[0],ijp_right[1]]
                sys.exit(' in streamfunction_init ')

            """
            -----------------------------------------------------------------------
             go forward in direction
            -----------------------------------------------------------------------
            """
            line_dir[isle,n,:] = Dir
            ij = ij + Dir
            if boundary[isle,1,1] == ij[0] and boundary[isle,1,2] == ij[1]:
                cont = False

            """
            -----------------------------------------------------------------------
             account for cyclic boundary conditions
            -----------------------------------------------------------------------
            """
            if enable_cyclic_x and Dir[0] == 1 and Dir[1] == 0 and ij[0] > nx:
                if verbose and my_pe == 0:
                    print ' shifting to western cyclic boundary'
                ij[0] -= nx
            if enable_cyclic_x and Dir[0] == -1 and Dir[1] == 0 and ij[0] < 1:
                if verbose and my_pe==0:
                    print ' shifting to eastern cyclic boundary'
                ij[0] += nx
            if boundary[isle,1,1] == ij[0] and boundary[isle,1,2] == ij[1]:
                cont = False

            if cont:
                n = n+1
                if n > max_boundary:
                    print 'increase value of max_boundary'
                    sys.exit(' in streamfunction_init ')
                boundary[isle,n,:] = ij

        nr_boundary[isle] = n
        if my_pe == 0:
            print ' number of points is ',n
        if verbose and my_pe == 0:
            print ' '
            print ' Positions:'
            for n in xrange(1, nr_boundary[n]): #n=1,nr_boundary(isle)
                print ' pos=',boundary[isle,n,:],' dir=',line_dir[isle,n,:]

    """
    -----------------------------------------------------------------------
     precalculate time independent boundary components of streamfunction
    -----------------------------------------------------------------------
    """
    forc[...] = 0.0
    for isle in xrange(1, nisle+1): #isle=1,nisle
        psin[:,:,isle] = 0.0
        for n in xrange(1, nr_boundary[isle]): #n=1,nr_boundary(isle)
            i = boundary[isle,n,1]
            j = boundary[isle,n,2]
            if i >= is_pe-onx and i <= ie_pe+onx and j >= js_pe-onx and j <= je_pe+onx:
                psin[i,j,isle] = 1.0
        #MPI stuff
        #call border_exchg_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,psin(:,:,isle));
        cyclic.setcyclic_xy   (is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,psin(:,:,isle))
        if my_pe == 0:
            print ' solving for boundary contribution by island ',isle

        congrad_streamfunction(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,forc,congr_itts,psin[:,:,isle],converged)
        if my_pe == 0:
            print ' itts =  ',congr_itts
        #MPI stuff
        #call border_exchg_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,psin(:,:,isle));
        cyclic.setcyclic_xy   (is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,psin(:,:,isle))

    """
    -----------------------------------------------------------------------
     precalculate time independent island integrals
    -----------------------------------------------------------------------
    """
    for n in xrange(1, nisle+1): #n=1,nisle
        for isle in xrange(1, nisle+1): #isle=1,nisle
            fpx[...] = 0
            fpy[...] = 0
            for j in xrange(js_pe-onx+1, je_pe+onx+1): #j=js_pe-onx+1,je_pe+onx
                for i in xrange(is_pe-onx+1, ie_pe+onx+1): #i=is_pe-onx+1,ie_pe+onx
                    fpx[i,j] =-maskU[i,j,nz]*( psin[i,j,isle]-psin[i,j-1,isle])/dyt[j]*hur[i,j]
                    fpy[i,j] = maskV[i,j,nz]*( psin[i,j,isle]-psin[i-1,j,isle])/(cosu[j]*dxt[i])*hvr[i,j]
            line_integral(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx, n,fpx,fpy,line_psin[n,isle])

def avoid_cyclic_boundaries(Map, boundary):
    for i in xrange(nx/2+1, nx+1): #i=nx/2+1,nx
        for j in xrange(ny+1): #j=0,ny
            if Map[i,j] == 1 and Map[i,j+1] == -1:
                #initial direction is eastward, we come from the west
                ij=[i,j]
                cont = True
                Dir = [1,0]
                boundary[isle,n,:] = [ij[0]-1,ij[1]]
                return (cont, ij, Dir)
            if Map[i,j] == -1 and Map[i,j+1] == 1:
                # initial direction is westward, we come from the east
                ij = [i-1,j]
                cont = True
                Dir = [-1,0]
                boundary[isle,n,:] = [ij[0]+1,ij[1]]
                return (cont, ij, Dir)
    return (False, None, None)

def avoid_cyclic_boundaries2():
    for i in xrange(nx/2,0,-1): #i=nx/2,1,-1  ! avoid starting close to cyclic bondaries
        for j in xrange(ny+1): #j=0,ny
            if Map[i,j] == 1 and Map[i,j+1] == -1:
                # initial direction is eastward, we come from the west
                ij=[i,j]
                cont = True
                Dir = [1,0]
                boundary[isle,n,:]= [ij[0]-1,ij[1]]
                return (cont, ij, Dir)
            if Map[i,j] == -1 and Map[i,j+1] == 1:
                # initial direction is westward, we come from the east
                ij=[i-1,j]
                cont = True
                Dir = [-1,0]
                boundary[isle,n,:] = [ij[0]+1,ij[1]]
                return (cont, ij, Dir)
    return (False, None, None)

def line_integral(is_,ie_,js_,je_,isle,uloc,vloc,line):
    """
    =======================================================================
     calculate line integral along island isle
    =======================================================================
    """
    #integer :: isle
    #integer :: js_,je_,is_,ie_
    #!real*8 :: uloc(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #!real*8 :: vloc(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8 :: uloc(is_:ie_,js_:je_)
    #real*8 :: vloc(is_:ie_,js_:je_)
    #real*8 :: line
    #integer :: n,i,j,nm1,js,je,is,ie
    line = 0
    Is = is_pe
    js = js_pe
    ie = ie_pe
    je = je_pe
    if Is == 1:
        Is -= 1
    if js == 1:
        js -= 1

    for n in xrange(1, nr_boundary[isle]): #n=1,nr_boundary(isle)
        nm1 = n-1
        if nm1 < 1:
            nm1 = nr_boundary[isle]
        i = boundary[isle,n,1]
        j = boundary[isle,n,2]
        if i >= Is and i <= ie and j >= js and j <= je:
            if line_dir[isle,n,1] == 1 and line_dir[isle,n,2] == 0:   # to east
                line += vloc[i,j]*dyu[j] + uloc[i,j+1]*dxu[i]*cost[j+1]
            elif line_dir[isle,n,1] == -1 and line_dir[isle,n,2] == 0: # to west
                line -= vloc[i+1,j]*dyu[j] - uloc[i,j]*dxu[i]*cost[j]
            elif line_dir[isle,n,1] == 0 and line_dir[isle,n,2] == 1: # to north
                line += vloc[i,j]*dyu[j]  - uloc[i,j]*dxu[i]*cost[j]
            elif line_dir[isle,n,1] ==  0 and line_dir[isle,n,2] == -1: # to south
                line += uloc[i,j+1]*dxu[i]*cost[j+1] - vloc[i+1,j]*dyu[j]
            else:
                print ' line_dir =',line_dir[isle,n,:],' at pos. ',boundary[isle,n,:]
                sys.exit(' missing line_dir in line integral')

def mod10(m):
    if m > 0:
        return m % 10
    else:
        return m

def showmap(is_,ie_,js_,je_,Map):
    #integer :: js_,je_,is_,ie_
    #!integer :: map(1-onx:nx+onx,1-onx:ny+onx)
    #integer :: map(is_:ie_,js_:je_)
    #integer,parameter :: linewidth=125
    #integer :: istart,iremain,isweep,iline,i,j,mod10
    #integer :: imt

    imt = nx +2*onx
    iremain = imt
    istart = 0
    print ' '*(5+min(linewidth,imt)/2-13),'Land mass and perimeter'
    for isweep in xrange(1, imt/linewidth + 2): #isweep=1,imt/linewidth + 1
        iline = min(iremain, linewidth)
        iremain = iremain - iline
        if iline > 0:
            print ' '
            print [istart+i+1-onx for i in xrange(1, iline, 6)]
            for j in xrange(ny+onx, -onx, -1): #j=ny+onx,1-onx,-1
                print j, [mod10(Map(istart+i -onx,j)) for i in xrange(1, iline+1)]
            print [istart+i+1-onx for i in xrange(1,iline+1,5)]
            #print '(t6,32i5)', (istart+i+4-onx,i=1,iline,5)
            istart = istart + iline
    print ' '

def solve_streamfunction():
    """
    =======================================================================
      solve for barotropic streamfunction
    =======================================================================
    """
    # use main_module
    # implicit none
    # integer :: i,j,k,isle
    # real*8 :: fxa,line_forc(nisle),line_psi0(nisle),aloc(nisle,nisle)
    # real*8 :: fpx(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    # real*8 :: fpy(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    # real*8 :: forc(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    # integer :: ipiv(nisle),info
    # logical :: converged

    #hydrostatic pressure
    fxa = grav/rho_0
    p_hydro[:,:,nz] = 0.5*rho[:,:,nz,tau]*fxa*dzw[nz]*maskT[:,:,nz]
    for k in xrange(nz-1, 0, -1): #k=nz-1,1,-1
        p_hydro[:,:,k] = maskT[:,:,k]*(p_hydro[:,:,k+1]+ 0.5*(rho[:,:,k+1,tau]+rho[:,:,k,tau])*fxa*dzw[k])

    # add hydrostatic pressure gradient
    for j in xrange(js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe+1): #i=is_pe,ie_pe
            du[i,j,:,tau] = du[i,j,:,tau] - ( p_hydro[i+1,j,:]-p_hydro[i,j,:]  )/(dxu[i]*cost[j]) *maskU[i,j,:]
            dv[i,j,:,tau] = dv[i,j,:,tau] - ( p_hydro[i,j+1,:]-p_hydro[i,j,:]  ) /dyu[j]*maskV[i,j,:]

    # forcing for barotropic streamfunction
    fpx = np.zeros(ie_pe-is_pe+2*onx, je_pe-js_pe+2*onx)
    fpy = np.zeros(ie_pe-is_pe+2*onx, je_pe-js_pe+2*onx)
    for k in xrange(nz): #k=1,nz
        fpx += (du[:,:,k,tau]+du_mix[:,:,k])*maskU[:,:,k]*dzt[k]
        fpy += (dv[:,:,k,tau]+dv_mix[:,:,k])*maskV[:,:,k]*dzt[k]

    fpx *= hur
    fpy *= hvr

    #MPI stuff
    #call border_exchg_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,fpx);
    cyclic.setcyclic_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,fpx)
    #call border_exchg_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,fpy);
    cyclic.setcyclic_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,fpy)

    for j in (js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe): #i=is_pe,ie_pe
            forc[i,j] = (fpy[i+1,j]-fpy[i,j])/(cosu[j]*dxu[i])-(cost[j+1]*fpx[i,j+1]-cost[j]*fpx[i,j])/(cosu[j]*dyu[j])

    # solve for interior streamfunction
    dpsi[:,:,taup1] = 2*dpsi[:,:,tau]-dpsi[:,:,taum1] # first guess, we need three time levels here
    congrad_streamfunction(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,forc,congr_itts,dpsi[:,:,taup1],converged)

    # MPI stuff
    #call border_exchg_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,dpsi(:,:,taup1))
    cyclic.setcyclic_xy   (is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,dpsi(:,:,taup1))

    if nisle > 1:
        # calculate island integrals of forcing, keep psi constant on island 1
        for k in xrange(2,nisle+1): #k=2,nisle
            line_integral(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx, k,fpx,fpy,line_forc[k])

        # calculate island integrals of interior streamfunction
        for k in xrange(2, nisle+1): #k=2,nisle
            fpx[...] = 0.0
            fpy[...] = 0.0
            for j in xrange(js_pe-onx+1, je_pe+onx+1): #j=js_pe-onx+1,je_pe+onx
                for i in xrange(is_pe-onx+1, ie_pe+onx+1): #i=is_pe-onx+1,ie_pe+onx
                    fpx[i,j] =-maskU[i,j,nz]*( dpsi[i,j,taup1]-dpsi[i,j-1,taup1])/dyt[j]*hur[i,j]
                    fpy[i,j] = maskV[i,j,nz]*( dpsi[i,j,taup1]-dpsi[i-1,j,taup1])/(cosu[j]*dxt[i])*hvr[i,j]
            line_integral(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx, k,fpx,fpy,line_psi0[k])

        line_forc -= line_psi0

        # solve for time dependent boundary values
        aloc = line_psin # will be changed in lapack routine
        #CALL DGESV(nisle-1 , 1, aloc(2:nisle,2:nisle), nisle-1, IPIV, line_forc(2:nisle), nisle-1, INFO )
        (lu, ipiv, line_forc[2:nisle], info) = scipy.linalg.lapack.dgesv(aloc[2:nisle, 2:nisle], line_forc[2:nisle])

        if info != 0:
            print 'info = ',info
            print ' line_forc=',line_forc[2:nisle]
            sys.exit(' in solve_streamfunction, lapack info not zero ')
        dpsin[2:nisle,tau] = line_forc[2:nisle]

    # integrate barotropic and baroclinic velocity forward in time
    psi[:,:,taup1] = psi[:,:,tau]+ dt_mom*( (1.5+AB_eps)*dpsi[:,:,taup1] - (0.5+AB_eps)*dpsi[:,:,tau] )
    for isle in xrange(2, nisle+1): #isle=2,nisle
        psi[:,:,taup1] = psi[:,:,taup1]+ dt_mom*( (1.5+AB_eps)*dpsin[isle,tau] - (0.5+AB_eps)*dpsin[isle,taum1])*psin[:,:,isle]
    u[:,:,:,taup1]   += dt_mom*( du_mix+ (1.5+AB_eps)*du[:,:,:,tau] - (0.5+AB_eps)*du[:,:,:,taum1] )*maskU
    v[:,:,:,taup1]   += dt_mom*( dv_mix+ (1.5+AB_eps)*dv[:,:,:,tau] - (0.5+AB_eps)*dv[:,:,:,taum1] )*maskV

    # subtract incorrect vertical mean from baroclinic velocity
    fpx[...] = 0.0
    fpy[...] = 0.0
    for k in xrange(1, nz+1): #k=1,nz
        fpx+=u[:,:,k,taup1]*maskU[:,:,k]*dzt[k]
        fpy+=v[:,:,k,taup1]*maskV[:,:,k]*dzt[k]
    for k in xrange(1, nz+1): #k=1,nz
        u[:,:,k,taup1] = u[:,:,k,taup1]-fpx*maskU[:,:,k]*hur
        v[:,:,k,taup1] = v[:,:,k,taup1]-fpy*maskV[:,:,k]*hvr

    # add barotropic mode to baroclinic velocity
    for j in xrange(js_pe, je_pe): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe): #i=is_pe,ie_pe
            u[i,j,:,taup1] -= maskU[i,j,:]*( psi[i,j,taup1]-psi[i,j-1,taup1])/dyt[j]*hur[i,j]
            v[i,j,:,taup1] += maskV[i,j,:]*( psi[i,j,taup1]-psi[i-1,j,taup1])/(cosu[j]*dxt[i])*hvr[i,j]


def make_coeff_streamfunction(is_, ie_, js_, je_, cf):
    """
    =======================================================================
             A * p = forc
             res = A * p
             res = res +  cf(...,ii,jj,kk) * p(i+ii,j+jj,k+kk)
    =======================================================================
    """
    #real*8 :: cf(is_:ie_,js_:je_,3,3)
    #cf = np.zeros(ie_-is_+1, je_-js_+1, 3, 3)
    for j in xrange(js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe+1): #i=is_pe,ie_pe
            cf[i,j, 0+2, 0+2] -= hvr[i+1,j]/dxu[i]/dxt[i+1] /cosu[j]**2
            cf[i,j, 1+2, 0+2] += hvr[i+1,j]/dxu[i]/dxt[i+1] /cosu[j]**2
            cf[i,j, 0+2, 0+2] -= hvr[i  ,j]/dxu[i]/dxt[i  ] /cosu[j]**2
            cf[i,j,-1+2, 0+2] += hvr[i  ,j]/dxu[i]/dxt[i  ] /cosu[j]**2

            cf[i,j, 0+2, 0+2] -= hur[i,j+1]/dyu[j]/dyt[j+1]*cost[j+1]/cosu[j]
            cf[i,j, 0+2, 1+2] += hur[i,j+1]/dyu[j]/dyt[j+1]*cost[j+1]/cosu[j]
            cf[i,j, 0+2, 0+2] -= hur[i,j  ]/dyu[j]/dyt[j  ]*cost[j  ]/cosu[j]
            cf[i,j, 0+2,-1+2] += hur[i,j  ]/dyu[j]/dyt[j  ]*cost[j  ]/cosu[j]




def congrad_streamfunction(is_,ie_,js_je_,forc,iterations,sol,converged):
    """
    =======================================================================
      conjugate gradient solver with preconditioner from MOM
    =======================================================================
    """
    #use main_module
    #implicit none
    #integer :: is_,ie_,js_,je_
    #integer :: iterations, n,i,j
    #!real*8  :: forc(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #!real*8  :: sol(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8  :: forc(is_:ie_,js_:je_)
    #real*8  :: sol(is_:ie_,js_:je_)
    #real*8  :: res(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8  :: Z(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8  :: Zres(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8  :: ss(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8  :: As(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8  :: estimated_error
    #real*8  :: zresmax,betakm1,betak,betak_min=0,betaquot,s_dot_As,smax
    #real*8  :: alpha,step,step1=0,convergence_rate
    #real*8 , external :: absmax_sfc,dot_sfc
    #logical, save :: first = .true.
    #real*8 , allocatable,save :: cf(:,:,:,:)
    #logical :: converged

    # congrad_streamfunction.first is basically like a static variable
    if congrad_streamfunction.first:
        cf = np.zeros((ie_pe+onx+1-(is_pe-onx), je_pe+onx+1-(js_pe-onx), 3, 3))
        make_coeff_streamfunction(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx, cf)
        congrad_streamfunction.first = False

    Z[...] = 0.
    Zres[...] = 0.
    ss[...] = 0.
    As[...] = 0.
    """
    -----------------------------------------------------------------------
         make approximate inverse operator Z (always even symmetry)
    -----------------------------------------------------------------------
    """
    make_inv_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,cf, Z)
    """
    -----------------------------------------------------------------------
         impose boundary conditions on guess
         sol(0) = guess
    -----------------------------------------------------------------------
    """
    # MPI stuff
    #call border_exchg_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,sol)
    cyclic.setcyclic_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,sol)
    """
    -----------------------------------------------------------------------
         res(0)  = forc - A * eta(0)
    -----------------------------------------------------------------------
    """
    solve_pressure.apply_op(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx, cf, sol, res)
    for j in xrange(js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe): #i=is_pe,ie_pe
            res[i,j] = forc[i,j] - res[i,j]
    """
    -----------------------------------------------------------------------
         Zres(k-1) = Z * res(k-1)
         see if guess is a solution, bail out to avoid division by zero
    -----------------------------------------------------------------------
    """
    n = 0
    inv_op_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,Z, res, Zres)
    Zresmax = absmax_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,Zres)
    # Assume convergence rate of 0.99 to extrapolate error
    if (100.0 * Zresmax < congr_epsilon):
        estimated_error = 100.0 * Zresmax
        info()
        return
    """
    -----------------------------------------------------------------------
         beta(0) = 1
         ss(0)    = zerovector()
    -----------------------------------------------------------------------
    """
    betakm1 = 1.0
    ss[...] = 0.
    """
    -----------------------------------------------------------------------
         begin iteration loop
    ----------------------------------------------------------------------
    """
    for n in xrange(1, congr_max_iterations): #n = 1,congr_max_iterations
        """
        -----------------------------------------------------------------------
               Zres(k-1) = Z * res(k-1)
        -----------------------------------------------------------------------
        """
        inv_op_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,Z, res, Zres)
        """
        -----------------------------------------------------------------------
               beta(k)   = res(k-1) * Zres(k-1)
        -----------------------------------------------------------------------
        """
        betak = dot_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,Zres, res)
        if n == 1:
            betak_min = abs(betak)
        elif n > 2:
            betak_min = min(betak_min, abs(betak))
            if abs(betak) > 100.0*betak_min:
                if my_pe == 0:
                    print 'WARNING: solver diverging at itt=',itt
                fail()
        """
        -----------------------------------------------------------------------
               ss(k)      = Zres(k-1) + (beta(k)/beta(k-1)) * ss(k-1)
        -----------------------------------------------------------------------
        """
        betaquot = betak/betakm1
        for j in xrange(js_pe,je_pe+1): #j=js_pe,je_pe
            for i in xrange(is_pe, ie_pe): #i=is_pe,ie_pe
                ss[i,j] = Zres[i,j] + betaquot*ss[i,j]
        #MPI stuff
        #call border_exchg_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,ss)
        cyclic.setcyclic_xy(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,ss)
        """
        -----------------------------------------------------------------------
               As(k)     = A * ss(k)
        -----------------------------------------------------------------------
        """
        solve_pressure.apply_op(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,cf, ss, As)
        """
        -----------------------------------------------------------------------
               If ss=0 then the division for alpha(k) gives a float exception.
               Assume convergence rate of 0.99 to extrapolate error.
               Also assume alpha(k) ~ 1.
        -----------------------------------------------------------------------
        """
        s_dot_As = dot_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,ss, As)
        if abs(s_dot_As) < abs(betak)*1.e-10:
            smax = absmax_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,ss)
            estimated_error = 100.0 * smax
            info()
            return
        """
        -----------------------------------------------------------------------
               alpha(k)  = beta(k) / (ss(k) * As(k))
        -----------------------------------------------------------------------
        """
        alpha = betak / s_dot_As
        """
        -----------------------------------------------------------------------
               update values:
               eta(k)   = eta(k-1) + alpha(k) * ss(k)
               res(k)    = res(k-1) - alpha(k) * As(k)
        -----------------------------------------------------------------------
        """
        for j in xrange(js_pe, je_pe):
            for i in xrange(is_pe, ie_pe):
                sol[i,j] += alpha * ss[i,j]
                res[i,j] -= alpha * As[i,j]

        smax = absmax_sfc(is_pe-onx,ie_pe+onx,js_pe-onx,je_pe+onx,ss)
        """
        -----------------------------------------------------------------------
               test for convergence
               if (estimated_error) < congr_epsilon) exit
        -----------------------------------------------------------------------
        """
        step = abs(alpha) * smax
        if n == 1:
            step1 = step
            estimated_error = step
            if step < congr_epsilon:
                info()
                return
        elif step < congr_epsilon:
            convergence_rate = np.exp(np.log(step/step1)/(n-1))
            estimated_error = step*convergence_rate/(1.0-convergence_rate)
            if estimated_error < congr_epsilon:
                info()
                return
        betakm1 = betak
    """
    -----------------------------------------------------------------------
         end of iteration loop
    -----------------------------------------------------------------------
    """
    if my_pe == 0:
        print ' WARNING: max iterations exceeded at itt=',itt
    fail()
congrad_streamfunction.first = True

def info(n, my_pe, estimated_error, congr_epsilon):
    converged = True
    if my_pe==0 and enable_congrad_verbose:
        print ' estimated error=',estimated_error,'/',congr_epsilon
        print ' iterations=',n

def fail(n, my_pe, estimated_error, congr_epsilon):
    converged = False
    if my_pe == 0:
        print ' estimated error=',estimated_error,'/',congr_epsilon
        print ' iterations=',n
    # check for NaN
    if np.isnan(estimated_error):
        if my_pe == 0:
            print ' error is NaN, stopping integration '
        #TODO: Snapshot data
        #call panic_snap
        sys.exit(' in solve_streamfunction')

def absmax_sfc(is_, ie_, js_, je_, p1):
    #use main_module
    #implicit none
    #integer :: is_,ie_,js_,je_
    #!real*8 :: s2,p1(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8 :: s2,p1(is_:ie_,js_:je_)
    #integer :: i,j
    s2 = 0
    for j in xrange(js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe+1): #i=is_pe,ie_pe
            s2 = max( abs(p1[i,j]), s2 )
    return s2

def dot_sfc(is_, ie_, js_, je_, p1, p2):
    #!real*8 :: s2,p1(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx),p2(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8 :: s2,p1(is_:ie_,js_:je_),p2(is_:ie_,js_:je_)
    #integer :: i,j
    s2 = 0
    for j in xrange(js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe+1): #i=is_pe,ie_pe
            s2 = s2+p1(i,j)*p2(i,j)
    return s2

def inv_op_sfc(is_,ie_,js_,je_,Z,res,Zres):
    """
    -----------------------------------------------------------------------
         apply approximate inverse Z of the operator A
    -----------------------------------------------------------------------
    """
    #integer :: is_,ie_,js_,je_
    #!real*8 :: Z(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #!real*8 :: res(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #!real*8 :: Zres(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8, dimension(is_:ie_,js_:je_) :: Z,res,Zres
    #integer :: i,j
    for j in xrange(js_pe,je_pe):
        for i in xrange(is_pe, ie_pe):
            Zres[i,j] = Z[i,j] * res[i,j]

def make_inv_sfc(is_,ie_,js_,je_,cf,Z):
    """
    -----------------------------------------------------------------------
         construct an approximate inverse Z to A
    -----------------------------------------------------------------------
    """
    #integer :: is_,ie_,js_,je_
    #!real*8 :: cf(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx,3,3)
    #!real*8 ::  Z(is_pe-onx:ie_pe+onx,js_pe-onx:je_pe+onx)
    #real*8 :: cf(is_:ie_,js_:je_,3,3)
    #real*8 :: Z (is_:ie_,js_:je_)
    #integer :: i,j,isle,n
#
#   copy diagonal coefficients of A to Z
#
    Z[...] = 0
    for j in xrange(js_pe, je_pe+1): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe+1): #i=is_pe,ie_pe
            Z[i,j] = cf[i,j,0+2,0+2]
#
#   now invert Z
#
    for j in xrange(js_pe, je_pe): #j=js_pe,je_pe
        for i in xrange(is_pe, ie_pe): #i=is_pe,ie_pe
            if Z[i,j] != 0.0:
                Z[i,j] = 1./Z[i,j]
            # Seems a bit redundant
            #else:
            #  Z(i,j) = 0.0
#
#   make inverse zero on island perimeters that are not integrated
#
    for isle in xrange(1, nisle+1): #isle=1,nisle
        for n in xrange(1, nr_boundary(isle)+1): #n=1,nr_boundary(isle)
            i = boundary(isle,n,1)
            j = boundary(isle,n,2)
            if i >= is_pe-onx and i <= ie_pe+onx and j >= js_pe-onx and j <= je_pe+onx:
                Z[i,j] = 0.0