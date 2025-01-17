import torch
import torch.optim as optim
from torch.optim.optimizer import Optimizer, required


def get_optimiser(models, mode, args):
    args.scaled_learning_rate = (args.learning_rate * (args.batch_size / 256))
    args.scaled_finetune_learning_rate = (args.finetune_learning_rate * (args.batch_size / 256))

    params_models = []
    reduced_params = []

    removed_params = []

    skip_lists = ['bn', 'bias']

    for m in models:

        m_skip = []
        m_noskip = []

        params_models += list(m.parameters())

        for name, param in m.named_parameters():
            if (any(skip_name in name for skip_name in skip_lists)):
                m_skip.append(param)
            else:
                m_noskip.append(param)
        reduced_params += list(m_noskip)
        removed_params += list(m_skip)
    # Set hyperparams depending on mode
    if mode == 'pretrain':
        lr = args.scaled_learning_rate
        wd = args.weight_decay
        opt = args.optimiser
    else:
        lr = args.scaled_finetune_learning_rate
        wd = args.finetune_weight_decay
        opt = args.finetune_optimiser

    # Select Optimiser
    if opt == 'adam':

        optimiser = optim.Adam(params_models, lr=lr,
                               weight_decay=wd)

    elif opt == 'sgd':

        optimiser = optim.SGD(params_models, lr=lr,
                              weight_decay=wd, momentum=0.9, nesterov=True)

    elif opt == 'lars':

        print("reduced_params len: {}".format(len(reduced_params)))
        print("removed_params len: {}".format(len(removed_params)))

        optimiser = LARS(reduced_params+removed_params, lr=lr,
                         weight_decay=wd, eta=0.001, use_nesterov=True, len_reduced=len(reduced_params))
    else:

        raise NotImplementedError('{} not setup.'.format(args.optimiser))

    return optimiser


class LARS(Optimizer):
    def __init__(self, params, lr, len_reduced, momentum=0.9, use_nesterov=False, weight_decay=0.0, classic_momentum=True, eta=0.001):

        self.epoch = 0
        defaults = dict(
            lr=lr,
            momentum=momentum,
            use_nesterov=use_nesterov,
            weight_decay=weight_decay,
            classic_momentum=classic_momentum,
            eta=eta,
            len_reduced=len_reduced
        )

        super(LARS, self).__init__(params, defaults)
        self.lr = lr
        self.momentum = momentum
        self.weight_decay = weight_decay
        self.use_nesterov = use_nesterov
        self.classic_momentum = classic_momentum
        self.eta = eta
        self.len_reduced = len_reduced

    def step(self, epoch=None, closure=None):

        loss = None

        if closure is not None:
            loss = closure()

        if epoch is None:
            epoch = self.epoch
            self.epoch += 1

        for group in self.param_groups:
            weight_decay = group['weight_decay']
            momentum = group['momentum']
            eta = group['eta']
            learning_rate = group['lr']

            # TODO: Hacky
            counter = 0
            for p in group['params']:
                if p.grad is None:
                    continue

                param = p.data
                grad = p.grad.data

                param_state = self.state[p]

                # TODO: This really hacky way needs to be improved.
                # Note Excluded are passed at the end of the list to are ignored
                if counter < self.len_reduced:
                    grad += self.weight_decay * param

                # Create parameter for the momentum
                if "momentum_var" not in param_state:
                    next_v = param_state["momentum_var"] = torch.zeros_like(
                        p.data
                    )
                else:
                    next_v = param_state["momentum_var"]

                if self.classic_momentum:
                    trust_ratio = 1.0

                    # TODO: implementation of layer adaptation
                    w_norm = torch.norm(param)
                    g_norm = torch.norm(grad)

                    device = g_norm.get_device()

                    trust_ratio = torch.where(w_norm.ge(0), torch.where(
                        g_norm.ge(0), (self.eta * w_norm / g_norm), torch.Tensor([1.0]).to(device)), torch.Tensor([1.0]).to(device)).item()

                    scaled_lr = learning_rate * trust_ratio

                    next_v.mul_(momentum).add_(scaled_lr, grad)

                    if self.use_nesterov:
                        update = (self.momentum * next_v) + (scaled_lr * grad)
                    else:
                        update = next_v

                    p.data.add_(-update)

                # Not classic_momentum
                else:

                    next_v.mul_(momentum).add_(grad)

                    if self.use_nesterov:
                        update = (self.momentum * next_v) + (grad)

                    else:
                        update = next_v

                    trust_ratio = 1.0

                    # TODO: implementation of layer adaptation
                    w_norm = torch.norm(param)
                    v_norm = torch.norm(update)

                    device = v_norm.get_device()

                    trust_ratio = torch.where(w_norm.ge(0), torch.where(
                        v_norm.ge(0), (self.eta * w_norm / v_norm), torch.Tensor([1.0]).to(device)), torch.Tensor([1.0]).to(device)).item()

                    scaled_lr = learning_rate * trust_ratio

                    p.data.add_(-scaled_lr * update)

                counter += 1

        return loss
